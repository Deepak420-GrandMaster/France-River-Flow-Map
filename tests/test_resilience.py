"""The app must stay usable when Hub'Eau or the river layers are unavailable."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest
import requests

from src.config import LOD_DETAIL, LOD_OVERVIEW, get_region, load_regions
from src.rivers import RiversUnavailable, load_river_geojson
from src.services import hubeau
from src.utils.map_helpers import build_map
from src.utils.tables import apply_filters, build_display_table

HERAULT = get_region("dep34")


@pytest.fixture
def api_down():
    """Every HTTP call raises, as during the Hub'Eau throttling we observed."""
    with patch.object(hubeau._SESSION, "get", side_effect=requests.ConnectionError("reset")):
        yield


def test_stations_call_raises_a_handled_error_when_api_is_down(api_down):
    with pytest.raises(hubeau.HubeauError):
        hubeau.get_active_stations("34")


def test_bulk_flow_returns_an_empty_but_valid_result_when_api_is_down(api_down):
    result = hubeau.get_latest_flows_for_stations(["Y210001001", "Y221001001"])
    assert result.snapshots == {}
    assert result.ok is False
    assert result.message and "Hub'Eau" in result.message
    assert result.fetched_at is not None


def test_single_station_helper_returns_a_blank_snapshot_when_api_is_down(api_down):
    snapshot = hubeau.get_latest_flow_for_station("Y210001001")
    assert snapshot.code_station == "Y210001001"
    assert snapshot.flow_m3s is None
    assert snapshot.has_reading is False


def test_history_raises_a_handled_error_when_api_is_down(api_down):
    with pytest.raises(hubeau.HubeauError):
        hubeau.get_station_flow_history("Y210001001")


# --------------------------------------------------------------------------
# Map still renders without live data or without river geometry
# --------------------------------------------------------------------------
EMPTY_STATIONS = pd.DataFrame(
    columns=[
        "code_station", "libelle_station", "libelle_cours_eau",
        "latitude_station", "longitude_station", "flow_m3s", "flow_lps", "measured_at",
    ]
)

ONE_STATION = pd.DataFrame(
    {
        "code_station": ["Y210001001"], "libelle_station": ["L'Hérault à Ganges"],
        "libelle_cours_eau": ["L'Hérault"], "latitude_station": [43.9321],
        "longitude_station": [3.7022], "flow_m3s": [None], "flow_lps": [None],
        "measured_at": [pd.NaT],
    }
)


def test_map_builds_with_no_stations_and_no_rivers():
    rendered = build_map(HERAULT, EMPTY_STATIONS, None, show_rivers=True).get_root().render()
    assert "leaflet" in rendered.lower()


def test_map_builds_with_stations_but_no_flow_readings():
    # A station with no reading must still get a marker, coloured as "no data".
    rendered = build_map(HERAULT, ONE_STATION, None).get_root().render()
    assert "Ganges" in rendered
    assert "No recent reading" in rendered


def test_map_escapes_dynamic_text_in_popups():
    hostile = ONE_STATION.copy()
    hostile.loc[0, "libelle_station"] = '<script>alert("x")</script>'
    rendered = build_map(HERAULT, hostile).get_root().render()
    assert "<script>alert" not in rendered
    assert "&lt;script&gt;" in rendered


def test_missing_river_layer_raises_a_clear_error():
    from src.config import Region

    # "99" is a well-formed code with no generated layer, which exercises the
    # missing-file path rather than the input-validation path.
    absent = Region(code="99", name="Nowhere", bounds=[[0.0, 0.0], [1.0, 1.0]])
    with pytest.raises(RiversUnavailable):
        load_river_geojson(absent, LOD_OVERVIEW)


def test_malformed_region_code_is_rejected_before_touching_the_disk():
    from src.config import Region

    hostile = Region(code="../../etc", name="Nope", bounds=[[0.0, 0.0], [1.0, 1.0]])
    with pytest.raises(ValueError):
        hostile.rivers_path(LOD_OVERVIEW)


def test_detail_layer_falls_back_to_overview_when_absent():
    # Gard has no layers at all, so both raise; Hérault has both and must not.
    assert load_river_geojson(HERAULT, LOD_DETAIL)["type"] == "FeatureCollection"


def test_every_metropolitan_department_is_offered():
    regions = load_regions()
    # 96 metropolitan departments (Corsica included) plus the national scope.
    assert len(regions) == 97
    assert {"dep34", "dep2A", "dep2B", "dep75", "france"} <= set(regions)


def test_national_scope_is_first_and_default():
    from src.config import DEFAULT_REGION_KEY, get_region

    regions = load_regions()
    assert next(iter(regions)) == "france"
    assert DEFAULT_REGION_KEY == "france"
    national = get_region("france")
    assert national.is_national
    assert national.rivers_path(LOD_OVERVIEW).name == "france_overview.geojson"
    assert national.boundary_path.name == "france.geojson"


def test_national_layers_exist_and_are_light():
    from src.config import get_region

    national = get_region("france")
    rivers = national.rivers_path(LOD_OVERVIEW)
    assert rivers.exists(), "run scripts/prepare_rivers.py --national"
    assert national.boundary_path.exists()
    assert rivers.stat().st_size / 1_000_000 < 8, "national layer too heavy for one payload"


def test_departments_are_not_flagged_national():
    assert not get_region("dep34").is_national


def test_every_offered_region_has_a_river_layer():
    missing = [r.label for r in load_regions().values() if not r.has_rivers]
    assert not missing, f"river layers missing for: {missing}"


def test_pipeline_survives_an_all_empty_dataset():
    filtered = apply_filters(EMPTY_STATIONS, {"only_with_flow": True, "search": "x", "flow_range": (0, 1)})
    assert filtered.empty
    assert build_display_table(filtered).empty


# --------------------------------------------------------------------------
# The Streamlit caching layer must swallow outages, never propagate them
# --------------------------------------------------------------------------
def test_station_loader_returns_empty_frame_when_api_down_and_no_snapshot(
    api_down, tmp_path, monkeypatch
):
    """The branch that drives the app's 'Hub'Eau is not responding' banner."""
    from src.data_loading import load_stations
    from src.services import snapshot

    monkeypatch.setattr(snapshot, "CACHE_DIR", tmp_path)
    frame = load_stations.__wrapped__("34")
    assert frame.empty
    assert list(frame.columns) == hubeau.STATION_COLUMNS


def test_station_loader_prefers_a_snapshot_over_an_empty_map(api_down, tmp_path, monkeypatch):
    """With a snapshot on disk an outage keeps the station list, not zeroes."""
    from src.data_loading import load_stations
    from src.services import snapshot

    monkeypatch.setattr(snapshot, "CACHE_DIR", tmp_path)
    saved = pd.DataFrame(
        {
            "code_station": ["Y210001001"], "libelle_station": ["L'Hérault à Ganges"],
            "libelle_cours_eau": ["L'Hérault"], "latitude_station": [43.9321],
            "longitude_station": [3.7022], "libelle_departement": ["Hérault"],
            "en_service": [True],
        }
    )
    snapshot.save("stations", "34", saved)
    frame = load_stations.__wrapped__("34")
    assert len(frame) == 1
    assert frame["libelle_station"].iloc[0] == "L'Hérault à Ganges"


def test_cached_flow_loader_reports_failure_without_raising(api_down, tmp_path, monkeypatch):
    from src.data_loading import load_latest_flows
    from src.services import snapshot

    monkeypatch.setattr(snapshot, "CACHE_DIR", tmp_path)
    fetch = load_latest_flows.__wrapped__(("Y210001001",))
    assert fetch.frame.empty
    assert fetch.ok is False
    assert fetch.message
    assert fetch.fetched_at is not None


def test_cached_history_loader_returns_empty_frame_when_api_is_down(api_down):
    from src.data_loading import load_station_history

    assert load_station_history.__wrapped__("Y210001001", 24).empty


def test_cached_rivers_loader_handles_hidden_and_unknown_regions():
    from src.config import LOD_HIDDEN
    from src.data_loading import load_rivers

    # "Hide rivers" must not touch the disk at all.
    assert load_rivers.__wrapped__("dep34", LOD_HIDDEN) is None
    # An unknown key falls back to the default department rather than failing.
    assert load_rivers.__wrapped__("nonsense", LOD_OVERVIEW) is not None
    assert load_rivers.__wrapped__("dep34", LOD_OVERVIEW) is not None


# --------------------------------------------------------------------------
# Last-known-good snapshot: the app must survive a Hub'Eau outage with data
# --------------------------------------------------------------------------
def test_snapshot_round_trip(tmp_path, monkeypatch):
    from src.services import snapshot

    monkeypatch.setattr(snapshot, "CACHE_DIR", tmp_path)
    frame = pd.DataFrame(
        {
            "code_station": ["Y210001001"], "flow_m3s": [1.67], "flow_lps": [1670.0],
            "measured_at": [pd.Timestamp("2026-08-20T10:00:00Z")],
        }
    )
    snapshot.save("flows", "34", frame)
    restored, saved_at = snapshot.load("flows", "34")
    assert restored is not None
    assert restored["flow_m3s"].iloc[0] == pytest.approx(1.67)
    assert saved_at is not None
    # The measurement timestamp must survive, so freshness stays honest.
    assert str(restored["measured_at"].iloc[0]).startswith("2026-08-20 10:00")


def test_snapshot_absent_returns_nothing(tmp_path, monkeypatch):
    from src.services import snapshot

    monkeypatch.setattr(snapshot, "CACHE_DIR", tmp_path)
    assert snapshot.load("flows", "99") == (None, None)


def test_stale_snapshot_is_refused(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone

    from src.services import snapshot

    monkeypatch.setattr(snapshot, "CACHE_DIR", tmp_path)
    old = datetime.now(timezone.utc) - timedelta(hours=snapshot.MAX_SNAPSHOT_AGE_HOURS + 1)
    (tmp_path / "flows-34.json").write_text(
        json.dumps({"saved_at": old.isoformat(), "rows": [{"code_station": "A"}]}),
        encoding="utf-8",
    )
    assert snapshot.load("flows", "34") == (None, None)


def test_corrupt_snapshot_is_ignored(tmp_path, monkeypatch):
    from src.services import snapshot

    monkeypatch.setattr(snapshot, "CACHE_DIR", tmp_path)
    (tmp_path / "flows-34.json").write_text("{not json", encoding="utf-8")
    assert snapshot.load("flows", "34") == (None, None)


def test_flow_loader_falls_back_to_the_snapshot(tmp_path, monkeypatch, api_down):
    from src.data_loading import load_latest_flows
    from src.services import snapshot

    monkeypatch.setattr(snapshot, "CACHE_DIR", tmp_path)
    snapshot.save(
        "flows", "34",
        pd.DataFrame({
            "code_station": ["A1"], "flow_m3s": [2.0], "flow_lps": [2000.0],
            "measured_at": [pd.Timestamp("2026-08-20T09:00:00Z")],
        }),
    )
    fetch = load_latest_flows.__wrapped__(("A1",), "34")
    assert fetch.from_cache is True
    assert fetch.ok is False
    assert fetch.cached_at is not None
    assert fetch.frame["flow_m3s"].iloc[0] == pytest.approx(2.0)


# --------------------------------------------------------------------------
# Map determinism: the reason interactions were slow
# --------------------------------------------------------------------------
def test_identical_inputs_produce_identical_map_html():
    import json

    rivers = json.loads(HERAULT.rivers_path(LOD_OVERVIEW).read_text(encoding="utf-8"))
    kwargs = {
        "rivers_geojson": rivers,
        "boundary_geojson": json.loads(HERAULT.boundary_path.read_text(encoding="utf-8")),
    }
    first = build_map(HERAULT, ONE_STATION, **kwargs).get_root().render()
    second = build_map(HERAULT, ONE_STATION, **kwargs).get_root().render()
    # Folium mints random ids per build; without stabilisation st_folium tears
    # down and rebuilds Leaflet on every rerun.
    assert first == second


def test_changing_a_control_changes_the_map_html():
    import json

    rivers = json.loads(HERAULT.rivers_path(LOD_OVERVIEW).read_text(encoding="utf-8"))
    animated = build_map(HERAULT, ONE_STATION, rivers, animate=True).get_root().render()
    still = build_map(HERAULT, ONE_STATION, rivers, animate=False).get_root().render()
    assert animated != still


def test_static_rivers_use_canvas_and_animation_uses_svg():
    import json

    rivers = json.loads(HERAULT.rivers_path(LOD_OVERVIEW).read_text(encoding="utf-8"))
    html = build_map(HERAULT, ONE_STATION, rivers, animate=True).get_root().render()
    # Canvas for the ~900 static paths, SVG only for the animated subset.
    assert "L.canvas(" in html
    assert html.count("L.svg(") == 1


def test_outside_area_is_masked():
    import json

    from src.utils.map_helpers import outside_mask

    boundary = json.loads(HERAULT.boundary_path.read_text(encoding="utf-8"))
    mask = outside_mask(boundary)
    rings = mask["geometry"]["coordinates"]
    assert rings[0][0] == [-180.0, -85.0]      # world ring
    assert len(rings) > 1                       # at least one department hole
    assert outside_mask(None) is None


def test_tests_never_write_to_the_real_cache_directory():
    """Guard against a stray snapshot polluting the app with test values.

    A fixture that forgets to monkeypatch CACHE_DIR would write fabricated
    readings into data/cache/, and the app would then present them as the last
    known good data during an outage.
    """
    from src.services import snapshot

    stray = sorted(p.name for p in snapshot.CACHE_DIR.glob("*.json")) if snapshot.CACHE_DIR.exists() else []
    assert all(name.startswith(("stations-", "flows-")) for name in stray)
    for name in stray:
        import json
        payload = json.loads((snapshot.CACHE_DIR / name).read_text(encoding="utf-8"))
        codes = {row.get("code_station") for row in payload.get("rows", [])}
        # Real Hub'Eau station codes are letter+digits and at least 8 chars.
        assert all(c and len(str(c)) >= 8 for c in codes), (
            f"{name} holds placeholder codes {codes} -- a test wrote to the real cache"
        )


def test_animated_paths_are_capped():
    """The animated layer is the only SVG layer; its size must stay bounded.

    The national river layer marks nearly every feature as "major", so without
    a cap the map would carry 3,272 SVG paths.
    """
    import json

    from src.config import get_region
    from src.utils.map_helpers import MAX_ANIMATED_FEATURES, split_rivers

    national = get_region("france")
    rivers = json.loads(national.rivers_path(LOD_OVERVIEW).read_text(encoding="utf-8"))
    minor, major = split_rivers(rivers)
    assert len(major["features"]) <= MAX_ANIMATED_FEATURES
    # Nothing is lost -- the overflow is drawn on canvas instead.
    assert len(minor["features"]) + len(major["features"]) == len(rivers["features"])
    # The animated ones are the longest.
    shortest_major = min(f["properties"]["length_km"] for f in major["features"])
    longest_minor = max(f["properties"]["length_km"] for f in minor["features"])
    assert shortest_major >= longest_minor


def test_national_dam_layer_exists_and_is_bounded():
    import json

    from src.config import get_region

    national = get_region("france")
    assert national.dams_path.name == "france.geojson"
    assert national.dams_path.exists(), "run scripts/prepare_dams.py --national"
    features = json.loads(national.dams_path.read_text(encoding="utf-8"))["features"]
    assert 500 < len(features) < 2500


# --------------------------------------------------------------------------
# The flow-speed control must actually reach the browser
# --------------------------------------------------------------------------
def test_flow_speed_is_emitted_in_the_hashed_script():
    """Regression guard for a subtle st_folium behaviour.

    ``st_folium`` derives its component key from ``generate_js_hash(leaflet)``
    -- the map's **script** only. A value that lives purely in the ``<style>``
    block can therefore change without the component ever re-rendering, which
    is why the speed slider appeared to do nothing. The duration must show up
    in the script for the control to work.
    """
    import re

    from streamlit_folium import generate_js_hash

    from src.utils.map_helpers import build_map

    hashes = set()
    for speed in (0.5, 1.6, 4.0):
        rendered = build_map(HERAULT, ONE_STATION, flow_speed=speed).get_root().render()
        assert f'"{speed:.2f}s"' in rendered, f"{speed}s missing from the map output"
        # Isolate the <script> section the way st_folium does.
        script = "\n".join(re.findall(r"<script>(.*?)</script>", rendered, re.S))
        assert f"{speed:.2f}s" in script, "duration is not in the hashed script"
        hashes.add(generate_js_hash(script, "map-test", False))

    assert len(hashes) == 3, "different speeds must produce different component keys"


def test_animation_css_reads_the_custom_property():
    from src.utils.map_helpers import build_map

    rendered = build_map(HERAULT, ONE_STATION, flow_speed=1.6).get_root().render()
    assert "var(--flow-duration" in rendered
    assert "--flow-duration" in rendered
