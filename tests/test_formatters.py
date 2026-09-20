"""Unit tests for presentation logic: colours, formatting, freshness, layers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.config import (
    FRESHNESS_DELAYED,
    FRESHNESS_RECENT,
    FRESHNESS_UNAVAILABLE,
    LOD_DETAIL,
    LOD_OVERVIEW,
    NO_DATA_COLOR,
    NORMAL_UNKNOWN_LABEL,
    flow_color,
    get_region,
    normal_ratio_color,
    normal_ratio_label,
)
from src.rivers import count_features, load_river_geojson, river_style
from src.utils.formatters import (
    add_freshness_column,
    format_commune,
    format_coordinates,
    format_flow,
    format_litres,
    format_timestamp,
    freshness,
    reading_age_minutes,
)
from src.utils.map_helpers import find_clicked_station, geojson_bounds

HERAULT = get_region("dep34")


@pytest.mark.parametrize(
    ("flow", "expected"),
    [(0.0, "#2c7fb8"), (0.99, "#2c7fb8"), (1.0, "#41ab5d"), (9.99, "#41ab5d"),
     (10.0, "#f0a202"), (99.9, "#f0a202"), (100.0, "#d7301f"), (5000.0, "#d7301f")],
)
def test_flow_colour_thresholds(flow, expected):
    assert flow_color(flow) == expected


def test_missing_flow_gets_the_no_data_colour():
    assert flow_color(None) == NO_DATA_COLOR


@pytest.mark.parametrize(
    ("flow", "expected"),
    [(None, "No recent reading"), (0.1234, "0.123 m³/s"), (5.432, "5.43 m³/s"), (1670.0, "1,670.0 m³/s")],
)
def test_flow_formatting_prioritises_m3s(flow, expected):
    assert format_flow(flow) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AGDE", "Agde"),
        ("FRAISSE-SUR-AGOUT", "Fraisse-sur-Agout"),
        ("SAINT-GUILHEM-LE-DESERT", "Saint-Guilhem-le-Desert"),
        ("PLOURIN-LES-MORLAIX", "Plourin-les-Morlaix"),
        ("CLERMONT-L'HERAULT", "Clermont-l'Herault"),
        # A particle only stays lowercase inside the name, never as its head.
        ("LES MATELLES", "Les Matelles"),
        ("L'ISLE-JOURDAIN", "L'Isle-Jourdain"),
        ("PONT-AVEN", "Pont-Aven"),
    ],
)
def test_commune_names_are_cased_as_french_place_names(raw, expected):
    assert format_commune(raw) == expected


def test_commune_formatting_invents_no_accents():
    """Hub'Eau publishes these unaccented. Guessing "Béziers" from "BEZIERS"
    would be inventing detail the source never provided -- and the guess is
    wrong often enough (Vedas/Védas, Menez/Ménez) to matter."""
    assert format_commune("BEZIERS") == "Beziers"
    assert format_commune("SAINT-JEAN-DE-VEDAS") == "Saint-Jean-de-Vedas"


def test_commune_formatting_handles_missing_values():
    assert format_commune(None) == ""
    assert format_commune("") == ""
    assert format_commune("   ") == ""
    assert format_commune(float("nan")) == ""


def test_timestamp_formatting_handles_missing_values():
    assert format_timestamp(None) == "—"
    assert format_timestamp(pd.NaT) == "—"
    assert format_timestamp(pd.Timestamp("2026-08-20T09:00:00Z")) == "2026-08-20 09:00 UTC"


STATIONS = pd.DataFrame(
    {
        "code_station": ["A1", "B2"],
        "latitude_station": [43.6100, 43.7000],
        "longitude_station": [3.8800, 3.9000],
    }
)


def test_click_matches_the_nearest_station():
    assert find_clicked_station(STATIONS, {"lat": 43.61001, "lng": 3.88002}) == "A1"


def test_click_far_from_any_station_selects_nothing():
    assert find_clicked_station(STATIONS, {"lat": 44.5, "lng": 3.0}) is None
    assert find_clicked_station(STATIONS, None) is None
    assert find_clicked_station(pd.DataFrame(columns=STATIONS.columns), {"lat": 43.61, "lng": 3.88}) is None


# --------------------------------------------------------------------------
# Generated river layers (skipped when preprocessing has not been run)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("level", [LOD_OVERVIEW, LOD_DETAIL])
def test_generated_river_layers_are_small_and_valid(level):
    # Detail layers are built on demand, so the loader falls back to overview.
    path = HERAULT.rivers_path(level)
    if not path.exists():
        path = HERAULT.rivers_path(LOD_OVERVIEW)
    assert path.exists(), "run scripts/prepare_rivers.py --all first"

    size_mb = path.stat().st_size / 1_000_000
    assert size_mb < 20, f"{path.name} is {size_mb:.1f} MB -- too heavy for Folium"

    geojson = load_river_geojson(HERAULT, level)
    assert geojson["type"] == "FeatureCollection"
    assert count_features(geojson) > 0

    feature = geojson["features"][0]
    assert set(feature["properties"]) >= {"name", "weight_class", "permanent", "length_km"}
    style = river_style(feature)
    assert style["color"].startswith("#") and style["weight"] > 0


def test_river_style_survives_missing_properties():
    assert river_style({})["weight"] > 0
    assert river_style({"properties": {"weight_class": None}})["weight"] > 0


# --------------------------------------------------------------------------
# Freshness classification
# --------------------------------------------------------------------------
NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("minutes_old", "expected"),
    [(0, FRESHNESS_RECENT), (45, FRESHNESS_RECENT), (90, FRESHNESS_RECENT),
     (91, FRESHNESS_DELAYED), (240, FRESHNESS_DELAYED)],
)
def test_freshness_threshold(minutes_old, expected):
    measured = NOW - timedelta(minutes=minutes_old)
    assert freshness(1.5, measured, now=NOW) == expected


def test_missing_reading_is_unavailable_not_stale():
    assert freshness(None, NOW, now=NOW) == FRESHNESS_UNAVAILABLE
    assert freshness(pd.NA, NOW, now=NOW) == FRESHNESS_UNAVAILABLE
    assert freshness(1.5, None, now=NOW) == FRESHNESS_UNAVAILABLE


def test_naive_timestamps_are_treated_as_utc():
    assert reading_age_minutes(pd.Timestamp("2026-08-20T11:00:00"), now=NOW) == pytest.approx(60.0)


def test_add_freshness_column_labels_every_row():
    frame = pd.DataFrame(
        {
            "flow_m3s": [1.0, 2.0, None],
            "measured_at": [NOW - timedelta(minutes=10), NOW - timedelta(hours=4), None],
        }
    )
    labelled = add_freshness_column(frame, now=NOW)
    assert list(labelled["freshness"]) == [FRESHNESS_RECENT, FRESHNESS_DELAYED, FRESHNESS_UNAVAILABLE]


def test_add_freshness_column_handles_empty_frame():
    empty = pd.DataFrame(columns=["flow_m3s", "measured_at"])
    assert "freshness" in add_freshness_column(empty).columns


def test_litres_formatting():
    assert format_litres(1670.0) == "1,670 L/s"
    assert format_litres(None) == "—"


def test_coordinate_formatting():
    assert format_coordinates(43.61234567, 3.88) == "43.6123, 3.8800"
    assert format_coordinates(None, 3.88) == "—"


def test_geojson_bounds_walks_nested_geometry():
    collection = {
        "type": "FeatureCollection",
        "features": [
            {"geometry": {"type": "LineString", "coordinates": [[3.0, 43.0], [3.5, 43.5]]}},
            {"geometry": {"type": "MultiLineString", "coordinates": [[[4.0, 44.0], [2.5, 42.9]]]}},
        ],
    }
    assert geojson_bounds(collection) == [[42.9, 2.5], [44.0, 4.0]]


def test_geojson_bounds_of_nothing_is_none():
    assert geojson_bounds(None) is None
    assert geojson_bounds({"type": "FeatureCollection", "features": []}) is None



# --------------------------------------------------------------------------
# Flow versus seasonal normal
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("ratio", "expected"),
    [(0.2, "Much below normal"), (0.49, "Much below normal"), (0.5, "Below normal"),
     (0.84, "Below normal"), (0.85, "Near normal"), (1.14, "Near normal"),
     (1.15, "Above normal"), (1.99, "Above normal"), (2.0, "Much above normal"),
     (12.0, "Much above normal")],
)
def test_normal_ratio_labels(ratio, expected):
    assert normal_ratio_label(ratio) == expected
    assert normal_ratio_color(ratio).startswith("#")


def test_unknown_normal_ratio_is_labelled_not_guessed():
    assert normal_ratio_label(None) == NORMAL_UNKNOWN_LABEL


# --------------------------------------------------------------------------
# Every department is usable
# --------------------------------------------------------------------------
def test_all_department_layers_are_individually_light():
    from src.config import load_regions

    heavy = []
    for region in load_regions().values():
        path = region.rivers_path(LOD_OVERVIEW)
        if path.exists() and path.stat().st_size / 1_000_000 > 5:
            heavy.append((region.label, path.stat().st_size / 1_000_000))
    assert not heavy, f"overview layers too heavy for Folium: {heavy}"


# --------------------------------------------------------------------------
# Internationalisation
# --------------------------------------------------------------------------
def test_every_string_has_both_languages():
    from src.i18n import LANGUAGES, STRINGS


    incomplete = [
        key for key, entry in STRINGS.items()
        if any(not entry.get(code) for code in LANGUAGES)
    ]
    assert not incomplete, f"missing translations: {incomplete}"


def test_translation_formats_placeholders():
    from src.i18n import t

    assert t("hero.dept", "fr", name="Hérault", code="34") == "Hérault · dép. 34"
    assert t("hero.dept", "en", name="Hérault", code="34") == "Hérault · dept. 34"


def test_unknown_key_returns_the_key_rather_than_raising():
    from src.i18n import t

    assert t("nope.missing", "fr") == "nope.missing"


def test_missing_placeholder_does_not_raise():
    """A translation used without its placeholders must degrade, not crash."""
    from src.i18n import STRINGS, t

    assert t("hero.dept", "en") == STRINGS["hero.dept"]["en"]


def test_freshness_labels_are_translated():
    from src.config import FRESHNESS_DELAYED, FRESHNESS_RECENT
    from src.utils.formatters import freshness_label

    assert freshness_label(FRESHNESS_RECENT, "en") == "Recent"
    assert freshness_label(FRESHNESS_RECENT, "fr") == "Récent"
    assert freshness_label(FRESHNESS_DELAYED, "fr") == "Différé"
    # An unknown code must degrade, not explode.
    assert freshness_label("bogus", "en") == "Unavailable"


def test_no_data_label_follows_the_language():
    from src.utils.formatters import format_flow

    assert format_flow(None, "en") == "No recent reading"
    assert format_flow(None, "fr") == "Aucune mesure récente"
