"""Streamlit-cached wrappers around the data services.

Caching lives here rather than in ``src/services`` so the service layer stays
a plain, testable Python module with no Streamlit dependency.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from src.config import LOD_HIDDEN, get_region
from src.rivers import RiversUnavailable, load_river_geojson
from src.services import hubeau, snapshot
from src.services.hubeau import HubeauError

#: Hub'Eau publishes new real-time readings every 5-60 minutes, so a 10-minute
#: cache is fresh enough while keeping load off a free public API.
LIVE_TTL_SECONDS = 600
#: The station reference list changes rarely.
REFERENCE_TTL_SECONDS = 3600
#: Seasonal normals are multi-year medians -- they do not move within a day.
NORMALS_TTL_SECONDS = 86_400


@dataclass(frozen=True)
class FlowFetch:
    """What the UI needs to know about one live-data refresh.

    ``from_cache`` marks readings restored from the on-disk snapshot after a
    failed fetch. They are real published measurements with their own
    timestamps, just not freshly retrieved -- the UI says so explicitly.
    """

    frame: pd.DataFrame
    ok: bool
    message: str
    fetched_at: datetime
    from_cache: bool = False
    cached_at: datetime | None = None


@st.cache_data(ttl=REFERENCE_TTL_SECONDS, show_spinner=False)
def load_stations(department_code: str) -> pd.DataFrame:
    """Active stations for a department.

    Falls back to the last successful snapshot when Hub'Eau is unreachable --
    the station list is a slowly-changing reference, so a day-old copy is
    materially better than an empty map.
    """
    try:
        frame = hubeau.get_active_stations(department_code)
    except HubeauError:
        cached, _ = snapshot.load("stations", department_code)
        return cached if cached is not None else hubeau.empty_stations()

    if not frame.empty:
        snapshot.save("stations", department_code, frame)
    return frame


FLOW_COLUMNS = ["code_station", "flow_m3s", "flow_lps", "measured_at"]


@st.cache_data(ttl=LIVE_TTL_SECONDS, show_spinner=False)
def load_latest_flows(station_codes: tuple[str, ...], department_code: str = "") -> FlowFetch:
    """Latest discharge per station, plus health metadata and a fetch timestamp.

    On a failed fetch the last successful snapshot is returned instead of an
    empty frame, flagged with ``from_cache`` so the UI can say where the
    numbers came from and when they were taken.
    """
    if not station_codes:
        return FlowFetch(pd.DataFrame(columns=FLOW_COLUMNS), True, "", datetime.now(timezone.utc))

    result = hubeau.get_latest_flows_for_stations(list(station_codes))
    if result.snapshots:
        frame = pd.DataFrame(
            [
                {
                    "code_station": reading.code_station,
                    "flow_m3s": reading.flow_m3s,
                    "flow_lps": reading.flow_lps,
                    "measured_at": reading.measured_at,
                }
                for reading in result.snapshots.values()
            ],
            columns=FLOW_COLUMNS,
        )
        if department_code:
            snapshot.save("flows", department_code, frame)
        return FlowFetch(frame, result.ok, result.message, result.fetched_at)

    cached, cached_at = snapshot.load("flows", department_code) if department_code else (None, None)
    if cached is not None:
        for column in FLOW_COLUMNS:
            if column not in cached.columns:
                cached[column] = pd.NA
        return FlowFetch(
            cached[FLOW_COLUMNS], False, "", result.fetched_at,
            from_cache=True, cached_at=cached_at,
        )

    message = result.message or (
        "Hub'Eau returned no recent readings. Station locations are still shown."
    )
    return FlowFetch(pd.DataFrame(columns=FLOW_COLUMNS), False, message, result.fetched_at)


@st.cache_data(ttl=NORMALS_TTL_SECONDS, show_spinner=False)
def load_seasonal_normals(station_codes: tuple[str, ...], month: int) -> pd.DataFrame:
    """Typical discharge for this calendar month, per station.

    Returns columns ``code_station``, ``normal_m3s``, ``normal_years``. An empty
    frame means the reference series could not be built -- never a guess.
    """
    columns = ["code_station", "normal_m3s", "normal_years"]
    if not station_codes:
        return pd.DataFrame(columns=columns)
    try:
        normals = hubeau.get_seasonal_normals(list(station_codes), month=month)
    except HubeauError:
        return pd.DataFrame(columns=columns)
    if not normals:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(
        [
            {
                "code_station": normal.code_station,
                "normal_m3s": normal.normal_m3s,
                "normal_years": normal.years,
            }
            for normal in normals.values()
        ],
        columns=columns,
    )


@st.cache_data(ttl=LIVE_TTL_SECONDS, show_spinner=False)
def load_station_history(code_station: str, hours: int) -> pd.DataFrame:
    """Discharge history for one station. Empty frame means 'nothing published'."""
    try:
        return hubeau.get_station_flow_history(code_station, hours=hours)
    except HubeauError:
        return pd.DataFrame(columns=["code_station", "date_obs", "resultat_obs", "flow_m3s"])


def _read_geojson(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@st.cache_data(show_spinner=False, max_entries=6)
def load_rivers(region_key: str, level_of_detail: str) -> dict | None:
    """Preprocessed river network. Cached, with a small ceiling on entries so
    browsing many departments cannot grow memory without bound."""
    if level_of_detail == LOD_HIDDEN:
        return None
    try:
        return load_river_geojson(get_region(region_key), level_of_detail)
    except (RiversUnavailable, OSError, ValueError):
        return None


@st.cache_data(show_spinner=False, max_entries=8)
def load_boundary(region_key: str) -> dict | None:
    return _read_geojson(get_region(region_key).boundary_path)


@st.cache_data(show_spinner=False, max_entries=8)
def load_dams(region_key: str) -> dict | None:
    """Dams, reservoirs and lakes for a department (BD TOPAGE PlanEau)."""
    return _read_geojson(get_region(region_key).dams_path)


def build_station_table(
    stations: pd.DataFrame, flows: pd.DataFrame, normals: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Left-join live readings (and optional normals) onto the station list.

    Stations without a reading keep NaN -- absence is never rendered as zero.
    """
    if stations.empty:
        return stations.assign(
            flow_m3s=pd.NA, flow_lps=pd.NA, measured_at=pd.NaT,
            normal_m3s=pd.NA, normal_years=pd.NA, normal_ratio=pd.NA,
        )

    merged = stations.merge(flows, on="code_station", how="left")
    for column in ("flow_m3s", "flow_lps"):
        if column not in merged.columns:
            merged[column] = pd.NA
    if "measured_at" not in merged.columns:
        merged["measured_at"] = pd.NaT

    if normals is not None and not normals.empty:
        merged = merged.merge(normals, on="code_station", how="left")
    else:
        merged["normal_m3s"] = pd.NA
        merged["normal_years"] = pd.NA

    flow = pd.to_numeric(merged["flow_m3s"], errors="coerce")
    normal = pd.to_numeric(merged["normal_m3s"], errors="coerce")
    # Guard against a zero normal: a ratio against zero is meaningless.
    merged["normal_ratio"] = (flow / normal.where(normal > 0)).astype(float)
    return merged


def utc_label(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")


AGE_WORDS = {
    "en": {"unknown": "unknown", "now": "just now", "min": "{n} min ago",
           "hour": "{n} h ago", "day": "{n} d ago"},
    "fr": {"unknown": "inconnu", "now": "à l'instant", "min": "il y a {n} min",
           "hour": "il y a {n} h", "day": "il y a {n} j"},
}


def relative_age(moment: datetime | None, lang: str = "en") -> str:
    """Compact 'x minutes ago' used by the header pill."""
    words = AGE_WORDS.get(lang, AGE_WORDS["en"])
    if moment is None:
        return words["unknown"]
    minutes = (datetime.now(timezone.utc) - moment).total_seconds() / 60
    if minutes < 1:
        return words["now"]
    if minutes < 60:
        return words["min"].format(n=int(minutes))
    hours = minutes / 60
    if hours < 24:
        return words["hour"].format(n=int(hours))
    return words["day"].format(n=int(hours / 24))


def clear_live_caches() -> None:
    """Drop only the live Hub'Eau caches.

    The preprocessed GeoJSON layers never change at runtime, so clearing them
    would just force a needless re-read of several MB from disk.
    """
    load_stations.clear()
    load_latest_flows.clear()
    load_station_history.clear()
    load_seasonal_normals.clear()
