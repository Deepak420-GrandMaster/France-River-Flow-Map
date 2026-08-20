"""Security-boundary tests.

Two untrusted inputs reach sensitive sinks in this app:

* **Department codes and level-of-detail strings** are interpolated into
  filesystem paths and into Hub'Eau query strings.
* **Station and river names come from a third-party API** and are rendered
  into HTML through ``unsafe_allow_html`` popups and panels.

Both are validated/escaped at the boundary, and these tests keep it that way.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.config import (
    Region,
    get_region,
    processed_path,
    validate_department_code,
)
from src.utils.map_helpers import build_map

HERAULT = get_region("dep34")


# --------------------------------------------------------------------------
# Path traversal
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "code",
    ["../../etc/passwd", "34/../../..", "..", "", "FR; rm -rf /", "%2e%2e%2f", "34\x00",
     "dep34", "1234", "a", None, 34],
)
def test_malformed_department_codes_are_rejected(code):
    with pytest.raises((ValueError, TypeError)):
        validate_department_code(code)


@pytest.mark.parametrize("code", ["01", "34", "2A", "2B", "95", "FR"])
def test_wellformed_department_codes_are_accepted(code):
    assert validate_department_code(code) == code


@pytest.mark.parametrize(
    "parts",
    [("..", "..", "etc", "passwd"), ("rivers", "..", "..", "..", "secrets"), ("/etc/passwd",)],
)
def test_processed_path_refuses_to_escape_the_data_directory(parts):
    with pytest.raises(ValueError):
        processed_path(*parts)


def test_processed_path_allows_legitimate_files():
    assert processed_path("rivers", "dep34_overview.geojson").name == "dep34_overview.geojson"


def test_level_of_detail_is_validated_before_reaching_a_filename():
    region = Region(code="34", name="Hérault", bounds=[[43.2, 2.5], [44.0, 4.2]])
    with pytest.raises(ValueError):
        region.rivers_path("../../../etc/passwd")
    with pytest.raises(ValueError):
        region.rivers_path("nonsense")


def test_region_paths_stay_inside_the_data_directory():
    from src.config import PROCESSED_DIR, load_regions

    root = PROCESSED_DIR.resolve()
    for region in load_regions().values():
        assert region.boundary_path.is_relative_to(root)
        assert region.dams_path.is_relative_to(root)
        assert region.rivers_path("overview").is_relative_to(root)


def test_hubeau_rejects_a_malformed_department_before_making_a_request():
    from unittest.mock import patch

    from src.services import hubeau

    with patch.object(hubeau, "_get_json") as fake:
        with pytest.raises(ValueError):
            hubeau.get_active_stations("../../etc")
    fake.assert_not_called()


# --------------------------------------------------------------------------
# HTML injection through API-supplied names
# --------------------------------------------------------------------------
HOSTILE = '<img src=x onerror="alert(1)">'
HOSTILE_ATTR = '"><script>alert(1)</script>'


def _station(**overrides) -> pd.DataFrame:
    row = {
        "code_station": "Y210001001", "libelle_station": "Normal",
        "libelle_cours_eau": "Normal", "latitude_station": 43.9,
        "longitude_station": 3.7, "flow_m3s": 1.5, "flow_lps": 1500.0,
        "measured_at": pd.Timestamp("2026-08-20T10:00:00Z"), "normal_ratio": 1.0,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def assert_payload_is_escaped(rendered: str, payload: str) -> None:
    """The raw payload must never survive into the document.

    Asserting on the literal payload rather than on the substring "<script>":
    folium's own output contains plenty of legitimate script tags, so a naive
    check passes trivially and proves nothing.
    """
    from html import escape

    # These two assertions together are the whole proof, and scanning for
    # fragments like "<script" or "onerror=" is not: folium's own output
    # legitimately contains <body>, <script> and the Leaflet attribution's
    # <img>, and an escaped payload still contains the literal text
    # "onerror=" inside &lt;...&gt; where it is inert.
    #
    #   1. the payload does not survive verbatim  -> it cannot be parsed as markup
    #   2. its escaped form is present            -> it was escaped, not silently dropped
    assert payload not in rendered, "raw payload rendered verbatim"
    assert escape(payload) in rendered, "payload neither escaped nor dropped"


@pytest.mark.parametrize("payload", [HOSTILE, HOSTILE_ATTR, "<b>bold</b>", "a & b"])
@pytest.mark.parametrize("field", ["libelle_station", "libelle_cours_eau", "code_station"])
def test_station_names_from_the_api_cannot_inject_html(field, payload):
    rendered = build_map(HERAULT, _station(**{field: payload})).get_root().render()
    assert_payload_is_escaped(rendered, payload)


def test_dam_names_from_the_source_data_cannot_inject_html():
    dams = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [3.7, 43.9]},
            "properties": {"name": HOSTILE, "category": HOSTILE_ATTR, "area_ha": 12.0},
        }],
    }
    rendered = build_map(
        HERAULT, _station(), show_dams=True, dams_geojson=dams
    ).get_root().render()
    assert_payload_is_escaped(rendered, HOSTILE)
    assert_payload_is_escaped(rendered, HOSTILE_ATTR)


#: A river name that tries to close the inline <script> block the GeoJSON is
#: embedded in. JSON does not escape "/", so plain json.dumps leaves this
#: intact and the browser stops parsing JavaScript and starts parsing HTML.
SCRIPT_BREAKOUT = "Rivière</script><script>window.__pwned=1</script>"


def _river_layer(name: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[3.6, 43.8], [3.7, 43.9]]},
            "properties": {"name": name, "weight_class": 3, "length_km": 40.0},
        }],
    }


@pytest.mark.parametrize("payload", [SCRIPT_BREAKOUT, HOSTILE, HOSTILE_ATTR])
def test_river_names_cannot_break_out_of_the_embedded_script(payload):
    """The river layer is serialised straight into an inline <script>."""
    rendered = build_map(
        HERAULT, _station(), rivers_geojson=_river_layer(payload), show_labels=True
    ).get_root().render()

    assert "</script><script>window.__pwned" not in rendered
    assert "<script>window.__pwned=1</script>" not in rendered
    # The dangerous characters must be unicode-escaped inside the JSON payload.
    assert payload not in rendered


def test_embedded_geojson_still_parses_back_to_the_original_value():
    """Escaping must not corrupt the data it protects."""
    import json

    from src.utils.flow_layer import embed_json

    for payload in (SCRIPT_BREAKOUT, HOSTILE, "Rivière d'Olt & Cie", "a\u2028b"):
        encoded = embed_json({"name": payload})
        assert "</script>" not in encoded
        assert json.loads(encoded)["name"] == payload


def test_river_label_markup_is_escaped():
    """Labels go through folium's DivIcon, which unicode-escapes the html."""
    rendered = build_map(
        HERAULT, _station(), rivers_geojson=_river_layer(HOSTILE), show_labels=True
    ).get_root().render()
    assert "river-label" in rendered
    # folium writes "<" as \u003c inside the divIcon html, so the raw tag can
    # never appear; the payload's own "<" is already an entity before that.
    assert HOSTILE not in rendered
    assert "u0026lt;img" in rendered


# --------------------------------------------------------------------------
# No secrets, no surprises
# --------------------------------------------------------------------------
def test_no_api_keys_or_tokens_in_the_source_tree():
    import re

    from src.config import PROJECT_ROOT

    suspicious = re.compile(
        r"(api[_-]?key|secret|passwd|password|bearer\s|AKIA[0-9A-Z]{16})\s*[=:]\s*[\"'][^\"']{8,}",
        re.IGNORECASE,
    )
    hits = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in path.parts for part in (".venv", ".archive_legacy", "tests")):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if suspicious.search(line):
                hits.append(f"{path.relative_to(PROJECT_ROOT)}:{number}")
    assert not hits, f"possible secret material: {hits}"


def test_error_details_are_hidden_from_the_browser():
    """A traceback in the UI leaks paths and internals to every visitor."""
    from src.config import PROJECT_ROOT

    config = (PROJECT_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert 'showErrorDetails = "none"' in config


def test_the_app_never_requests_a_non_hubeau_host_at_runtime():
    from src.services import hubeau

    for url in (hubeau.STATIONS_ENDPOINT, hubeau.OBSERVATIONS_ENDPOINT, hubeau.OBS_ELAB_ENDPOINT):
        assert url.startswith("https://hubeau.eaufrance.fr/")
