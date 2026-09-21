"""Unit tests for station filtering and the display table."""

from __future__ import annotations

import pandas as pd
import pytest

from src.utils.tables import (
    TABLE_COLUMNS,
    apply_filters,
    build_display_table,
    city_options,
    departments_for_cities,
    national_city_options,
    stations_for_cities,
)

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


# --------------------------------------------------------------------------
# City filter options
# --------------------------------------------------------------------------
def _cities(**columns) -> pd.DataFrame:
    return pd.DataFrame(columns)


def test_city_options_pair_the_raw_value_with_a_readable_label():
    """The value must stay as published -- that is what apply_filters matches."""
    options = city_options(_cities(
        libelle_commune=["SAINT-GUILHEM-LE-DESERT", "AGDE"],
        code_departement=["34", "34"],
    ))
    assert options == [("AGDE", "Agde"), ("SAINT-GUILHEM-LE-DESERT", "Saint-Guilhem-le-Desert")]


def test_city_options_are_sorted_by_the_label_not_the_raw_value():
    options = city_options(_cities(
        libelle_commune=["BEZIERS", "AGDE", "MONTPELLIER"],
        code_departement=["34", "34", "34"],
    ))
    assert [label for _, label in options] == ["Agde", "Beziers", "Montpellier"]


def test_a_commune_name_shared_by_two_departments_is_disambiguated():
    """Nationally, 27 of ~3,100 gauged commune names occur in more than one
    department. Without the suffix those entries are indistinguishable."""
    options = dict(city_options(_cities(
        libelle_commune=["SAINT-MARTIN", "SAINT-MARTIN", "AGDE"],
        code_departement=["17", "65", "34"],
    )))
    assert options["SAINT-MARTIN"] == "Saint-Martin (17, 65)"
    # The unambiguous ones stay clean -- suffixing everything would be noise.
    assert options["AGDE"] == "Agde"


def test_city_options_are_clean_within_a_single_department():
    options = city_options(_cities(
        libelle_commune=["MONTPELLIER", "AGDE"], code_departement=["34", "34"],
    ))
    assert [label for _, label in options] == ["Agde", "Montpellier"]


def test_city_options_ignore_blank_and_missing_names():
    options = city_options(_cities(
        libelle_commune=["AGDE", None, "   "], code_departement=["34", "34", "34"],
    ))
    assert options == [("AGDE", "Agde")]


def test_city_options_survive_a_frame_without_the_column():
    """Station snapshots predating the commune field have no such column."""
    assert city_options(_cities(code_station=["Y1"])) == []
    assert city_options(pd.DataFrame()) == []


# --------------------------------------------------------------------------
# National view: the committed commune registry, and what a choice costs
# --------------------------------------------------------------------------
#: Shape of src.config.load_communes(): raw name -> departments it occurs in.
COMMUNES = {
    "TOULOUSE": ("31",),
    "AGDE": ("34",),
    "MONTPELLIER": ("34",),
    "LYON": ("69",),
    "SAINT-MARTIN": ("17", "65"),
}

NATIONAL = pd.DataFrame(
    {
        "code_station": ["Y0", "Y1", "Y2", "Y3"],
        "libelle_commune": ["TOULOUSE", "TOULOUSE", "AGDE", "MONTPELLIER"],
        "code_departement": ["31", "31", "34", "34"],
    }
)


def test_national_options_come_from_the_registry_not_from_stations():
    """The national view has no stations loaded -- that is the point of the
    registry -- so its list cannot be derived from a frame."""
    options = dict(national_city_options(COMMUNES))
    assert options["AGDE"] == "Agde"
    assert options["TOULOUSE"] == "Toulouse"
    # Same disambiguation rule as the department views.
    assert options["SAINT-MARTIN"] == "Saint-Martin (17, 65)"


def test_national_options_are_sorted_by_label():
    labels = [label for _, label in national_city_options(COMMUNES)]
    assert labels == sorted(labels)


def test_a_missing_registry_offers_nothing_rather_than_failing():
    assert national_city_options({}) == []


def test_departments_for_cities_is_what_the_request_cost_is_measured_in():
    """One Hub'Eau request per department, however many communes were chosen
    inside it -- so two cities in one department cost one request."""
    assert departments_for_cities(COMMUNES, ["AGDE", "MONTPELLIER"]) == ["34"]
    assert departments_for_cities(COMMUNES, ["AGDE", "LYON"]) == ["34", "69"]


def test_a_commune_in_two_departments_needs_both():
    assert departments_for_cities(COMMUNES, ["SAINT-MARTIN"]) == ["17", "65"]


def test_unknown_or_empty_cities_need_no_departments():
    assert departments_for_cities(COMMUNES, []) == []
    assert departments_for_cities(COMMUNES, ["ATLANTIS"]) == []


def test_no_city_chosen_shows_nothing_nationally():
    """Empty means "nothing yet", not "everything": the national view does not
    load readings for every gauging station in France."""
    result = stations_for_cities(NATIONAL, [])
    assert result.empty
    # The columns survive, so the caller needs no special case for empty.
    assert list(result.columns) == list(NATIONAL.columns)


def test_chosen_cities_select_their_stations():
    result = stations_for_cities(NATIONAL, ["TOULOUSE", "AGDE"])
    assert sorted(result["code_station"]) == ["Y0", "Y1", "Y2"]


def test_only_the_chosen_communes_survive_a_loaded_department():
    """A department is loaded whole, then narrowed: Montpellier must not drag
    in the rest of the Hérault."""
    result = stations_for_cities(NATIONAL, ["MONTPELLIER"])
    assert list(result["code_station"]) == ["Y3"]


def test_blank_entries_in_the_selection_are_ignored():
    assert stations_for_cities(NATIONAL, ["", None]).empty


def test_selection_is_skipped_when_the_commune_column_is_absent():
    legacy = NATIONAL.drop(columns=["libelle_commune"])
    assert stations_for_cities(legacy, ["TOULOUSE"]).empty
