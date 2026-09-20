"""Station filtering and tabular presentation.

Separated from ``app.py`` so the filter and table rules can be unit-tested
without starting a Streamlit runtime.
"""

from __future__ import annotations

import pandas as pd

from src.i18n import DEFAULT_LANGUAGE, t
from src.utils.formatters import freshness_label

#: Column order is fixed; only the headings are translated.
TABLE_KEYS = [
    "table.station", "table.river", "table.code",
    "table.discharge", "table.observed", "table.freshness",
]
TABLE_COLUMNS = [t(key) for key in TABLE_KEYS]


def table_columns(lang: str = DEFAULT_LANGUAGE) -> list[str]:
    return [t(key, lang) for key in TABLE_KEYS]


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
