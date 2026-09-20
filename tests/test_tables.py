"""Unit tests for station filtering and the display table."""

from __future__ import annotations

import pandas as pd
import pytest

from src.utils.tables import TABLE_COLUMNS, apply_filters, build_display_table

STATIONS = pd.DataFrame(
    {
        "libelle_station": [
            "L'Orb à Béziers", "L'Hérault à Ganges", "Le Lez à Montpellier", "La Mosson à Juvignac",
        ],
        "libelle_cours_eau": ["L'Orb", "L'Hérault", "Le Lez", "La Mosson"],
        "code_station": ["Y2580", "Y2100", "Y3204", "Y3315"],
        # Stored exactly as Hub'Eau publishes it: shouted. Filtering matches
        # these raw values; only the sidebar labels are cased for display.
        "libelle_commune": ["BEZIERS", "GANGES", "MONTPELLIER", "JUVIGNAC"],
        "flow_m3s": [3.13, 1.65, None, 0.02],
        "measured_at": [
            pd.Timestamp("2026-08-20T10:10:00Z"), pd.Timestamp("2026-08-20T10:00:00Z"),
            pd.NaT, pd.Timestamp("2026-08-20T09:00:00Z"),
        ],
        "freshness": ["Recent", "Recent", "Unavailable", "Delayed"],
    }
)

NO_FILTERS = {"only_with_flow": False, "search": "", "flow_range": None}


def test_no_filters_keeps_everything():
    assert len(apply_filters(STATIONS, NO_FILTERS)) == 4


def test_only_with_flow_drops_stations_without_a_reading():
    result = apply_filters(STATIONS, {**NO_FILTERS, "only_with_flow": True})
    assert list(result["code_station"]) == ["Y2580", "Y2100", "Y3315"]


def test_city_filter_keeps_only_the_selected_communes():
    result = apply_filters(STATIONS, {**NO_FILTERS, "cities": ["MONTPELLIER", "GANGES"]})
    assert sorted(result["code_station"]) == ["Y2100", "Y3204"]


def test_empty_city_selection_means_every_city():
    """The multiselect starts empty, and empty must not mean "no stations"."""
    assert len(apply_filters(STATIONS, {**NO_FILTERS, "cities": []})) == 4


def test_city_filter_is_skipped_when_the_column_is_absent():
    """Station snapshots written before the commune field was requested stay
    readable for 48 hours, and have no libelle_commune column at all.

    Dropping every row there would look like an outage rather than a stale
    cache, so an unfilterable frame is left alone.
    """
    legacy = STATIONS.drop(columns=["libelle_commune"])
    assert len(apply_filters(legacy, {**NO_FILTERS, "cities": ["MONTPELLIER"]})) == 4


def test_city_filter_combines_with_the_other_filters():
    result = apply_filters(
        STATIONS,
        {**NO_FILTERS, "cities": ["MONTPELLIER", "BEZIERS"], "only_with_flow": True},
    )
    # Le Lez à Montpellier has no reading, so only Béziers survives both.
    assert list(result["code_station"]) == ["Y2580"]


def test_search_matches_station_river_and_code_case_insensitively():
    assert list(apply_filters(STATIONS, {**NO_FILTERS, "search": "orb"})["code_station"]) == ["Y2580"]
    assert list(apply_filters(STATIONS, {**NO_FILTERS, "search": "HÉRAULT"})["code_station"]) == ["Y2100"]
    assert list(apply_filters(STATIONS, {**NO_FILTERS, "search": "y3204"})["code_station"]) == ["Y3204"]


def test_search_with_no_match_returns_empty():
    assert apply_filters(STATIONS, {**NO_FILTERS, "search": "loire"}).empty


def test_search_treats_regex_characters_literally():
    # A stray "(" must not raise; it simply matches nothing.
    assert apply_filters(STATIONS, {**NO_FILTERS, "search": "("}).empty


def test_flow_range_keeps_unknown_readings():
    result = apply_filters(STATIONS, {**NO_FILTERS, "flow_range": (1.0, 5.0)})
    # Y3315 (0.02) is out of range; the None reading (Y3204) is preserved,
    # because only the dedicated toggle is allowed to hide unknowns.
    assert set(result["code_station"]) == {"Y2580", "Y2100", "Y3204"}


def test_flow_range_and_toggle_combine():
    result = apply_filters(
        STATIONS, {"only_with_flow": True, "search": "", "flow_range": (1.0, 5.0)}
    )
    assert set(result["code_station"]) == {"Y2580", "Y2100"}


def test_filters_on_empty_frame_are_safe():
    empty = STATIONS.iloc[0:0]
    assert apply_filters(empty, {**NO_FILTERS, "search": "orb"}).empty


def test_display_table_is_sorted_by_discharge_descending():
    table = build_display_table(STATIONS)
    assert list(table["Code"]) == ["Y2580", "Y2100", "Y3315", "Y3204"]
    assert list(table.columns) == TABLE_COLUMNS


def test_display_table_renders_missing_values_as_blanks():
    table = build_display_table(STATIONS)
    last = table.iloc[-1]
    assert pd.isna(last["Discharge (m³/s)"])
    assert last["Observed at (UTC)"] == ""
    assert last["Freshness"] == "Unavailable"


def test_display_table_trims_timestamps_to_minutes():
    assert build_display_table(STATIONS)["Observed at (UTC)"].iloc[0] == "2026-08-20 10:10"


def test_display_table_rounds_discharge():
    frame = STATIONS.copy()
    frame.loc[0, "flow_m3s"] = 1.23456789
    assert build_display_table(frame)["Discharge (m³/s)"].max() == pytest.approx(1.65)
    assert 1.235 in set(build_display_table(frame)["Discharge (m³/s)"].dropna())


def test_display_table_of_empty_frame_keeps_columns():
    assert list(build_display_table(pd.DataFrame()).columns) == TABLE_COLUMNS


def test_display_table_csv_round_trip_has_no_none_strings():
    csv = build_display_table(STATIONS).to_csv(index=False)
    assert "None" not in csv
    assert "+00:00" not in csv
