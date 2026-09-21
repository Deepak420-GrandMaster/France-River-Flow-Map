"""Station filtering and tabular presentation.

Separated from ``app.py`` so the filter and table rules can be unit-tested
without starting a Streamlit runtime.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from src.i18n import DEFAULT_LANGUAGE, t
from src.utils.formatters import format_commune, freshness_label

#: Column order is fixed; only the headings are translated.
TABLE_KEYS = [
    "table.station", "table.river", "table.code",
    "table.discharge", "table.observed", "table.freshness",
]
TABLE_COLUMNS = [t(key) for key in TABLE_KEYS]


def table_columns(lang: str = DEFAULT_LANGUAGE) -> list[str]:
    return [t(key, lang) for key in TABLE_KEYS]


def _labelled(departments: dict[str, Sequence[str]]) -> list[tuple[str, str]]:
    """Turn ``{raw name: departments}`` into sorted ``(value, label)`` pairs.

    The value stays exactly as Hub'Eau published it, because that is what
    :func:`apply_filters` matches on; only the label is cased for reading, and
    sorting follows the label so the list reads alphabetically as shown.

    A label carries its department codes only when the same commune name
    occurs in more than one department -- 26 of the ~3,100 gauged communes in
    France. Suffixing every label would be noise on a department view where
    the department is already fixed; suffixing none would leave those 26
    indistinguishable in the national list.
    """
    options = []
    for name in sorted(departments, key=format_commune):
        label = format_commune(name)
        shared = sorted(departments[name])
        if len(shared) > 1:
            label = f"{label} ({', '.join(shared)})"
        options.append((name, label))
    return options


def city_options(stations: pd.DataFrame) -> list[tuple[str, str]]:
    """City filter options derived from a loaded station frame.

    Used by the department views, where the stations on screen are exactly the
    communes worth offering.
    """
    if stations is None or stations.empty or "libelle_commune" not in stations.columns:
        return []

    names = stations["libelle_commune"].fillna("").astype(str).str.strip()
    keep = names != ""
    if not keep.any():
        return []

    codes = (
        stations["code_departement"].fillna("").astype(str).str.strip()
        if "code_departement" in stations.columns
        else pd.Series("", index=stations.index)
    )
    departments: dict[str, set[str]] = {name: set() for name in names[keep]}
    for name, code in zip(names[keep], codes[keep]):
        if code:
            departments[name].add(code)
    return _labelled(departments)


def national_city_options(communes: dict[str, Sequence[str]]) -> list[tuple[str, str]]:
    """City filter options for the national view, from the commune registry.

    The national view has no stations loaded to derive a list from -- that is
    the whole point of the registry -- so the options come from
    ``src.config.load_communes`` instead.
    """
    return _labelled(communes or {})


def departments_for_cities(
    communes: dict[str, Sequence[str]], cities: Sequence[str]
) -> list[str]:
    """Departments that have to be loaded to cover ``cities``.

    This is what the national view's cost is measured in: one Hub'Eau request
    per department, regardless of how many communes inside it were chosen.
    """
    needed: set[str] = set()
    for city in cities or []:
        needed.update(communes.get(city, ()))
    return sorted(needed)


def stations_for_cities(stations: pd.DataFrame, cities: Sequence[str]) -> pd.DataFrame:
    """The subset of ``stations`` sited in ``cities``.

    Nothing chosen means nothing shown, not everything: on the national view a
    city is what turns stations on at all. The frame keeps its columns either
    way, so callers never special-case "empty".
    """
    if stations is None or stations.empty:
        return stations

    chosen = [city for city in (cities or []) if city]
    if not chosen or "libelle_commune" not in stations.columns:
        return stations.iloc[0:0]
    return stations[stations["libelle_commune"].isin(chosen)]


def apply_filters(stations: pd.DataFrame, controls: dict) -> pd.DataFrame:
    """Filter the station table according to the sidebar state.

    ``controls`` keys: ``only_with_flow`` (bool), ``cities`` (list of raw
    ``libelle_commune`` values), ``search`` (str), ``flow_range``
    (``(low, high)`` in m³/s, or ``None``).
    """
    if stations.empty:
        return stations
    filtered = stations

    if controls.get("only_with_flow"):
        filtered = filtered[filtered["flow_m3s"].notna()]

    cities = controls.get("cities") or []
    # The column is absent from station snapshots written before the commune
    # field was requested, and those stay readable for 48 hours. An empty
    # selection is "all cities", so only a real selection can filter.
    if cities and "libelle_commune" in filtered.columns:
        filtered = filtered[filtered["libelle_commune"].isin(cities)]

    search = (controls.get("search") or "").strip()
    if search:
        needle = search.casefold()
        haystack = (
            filtered["libelle_station"].fillna("").astype(str).str.casefold()
            + " "
            + filtered["libelle_cours_eau"].fillna("").astype(str).str.casefold()
            + " "
            + filtered["code_station"].fillna("").astype(str).str.casefold()
        )
        filtered = filtered[haystack.str.contains(needle, regex=False)]

    flow_range = controls.get("flow_range")
    if flow_range is not None:
        low, high = flow_range
        in_range = filtered["flow_m3s"].between(low, high)
        # Stations with no reading are only removed by the dedicated toggle,
        # so a discharge range never silently hides "unknown".
        filtered = filtered[in_range | filtered["flow_m3s"].isna()]

    return filtered


def build_display_table(stations: pd.DataFrame, lang: str = DEFAULT_LANGUAGE) -> pd.DataFrame:
    """Filtered station table, sorted by latest discharge descending.

    Missing readings render as an empty cell rather than the string "None",
    and timestamps are trimmed to minutes -- the raw values carry a redundant
    "+00:00" offset that adds noise without adding information.
    """
    headings = table_columns(lang)
    if stations.empty:
        return pd.DataFrame(columns=headings)

    ordered = stations.sort_values("flow_m3s", ascending=False, na_position="last")
    return pd.DataFrame(
        {
            headings[0]: ordered["libelle_station"].astype("string"),
            headings[1]: ordered["libelle_cours_eau"].astype("string"),
            headings[2]: ordered["code_station"].astype("string"),
            # Numeric dtype keeps the column sortable in st.dataframe.
            headings[3]: pd.to_numeric(ordered["flow_m3s"], errors="coerce").round(3),
            headings[4]: [
                "" if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")
                for value in ordered["measured_at"]
            ],
            headings[5]: [freshness_label(state, lang) for state in ordered["freshness"]],
        }
    ).reset_index(drop=True)
