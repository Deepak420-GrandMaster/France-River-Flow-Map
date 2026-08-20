"""Formatting and classification helpers shared by the map, table and charts.

Kept free of Streamlit and Folium imports so they are trivially testable.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from src.config import (
    FRESH_MINUTES,
    FRESHNESS_DELAYED,
    FRESHNESS_RECENT,
    FRESHNESS_UNAVAILABLE,
)
from src.i18n import DEFAULT_LANGUAGE, t

#: Internal freshness codes -> translation keys. The stored value stays in
#: English so filtering and tests never depend on the display language.
FRESHNESS_KEYS = {
    FRESHNESS_RECENT: "fresh.recent",
    FRESHNESS_DELAYED: "fresh.delayed",
    FRESHNESS_UNAVAILABLE: "fresh.unavailable",
}


def freshness_label(state: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """Display text for a freshness code."""
    return t(FRESHNESS_KEYS.get(state, "fresh.unavailable"), lang)


def format_flow(flow_m3s: float | None, lang: str = DEFAULT_LANGUAGE) -> str:
    """Human-readable discharge. m³/s is the headline unit everywhere in the UI."""
    if flow_m3s is None or pd.isna(flow_m3s):
        return t("flow.none", lang)
    flow_m3s = float(flow_m3s)
    if flow_m3s >= 10:
        return f"{flow_m3s:,.1f} m³/s"
    if flow_m3s >= 1:
        return f"{flow_m3s:.2f} m³/s"
    return f"{flow_m3s:.3f} m³/s"


def format_litres(flow_lps: float | None) -> str:
    """Secondary display of the raw published value."""
    if flow_lps is None or pd.isna(flow_lps):
        return "—"
    return f"{float(flow_lps):,.0f} L/s"


def format_timestamp(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M UTC")


def format_coordinates(latitude: float | None, longitude: float | None) -> str:
    if latitude is None or longitude is None or pd.isna(latitude) or pd.isna(longitude):
        return "—"
    return f"{float(latitude):.4f}, {float(longitude):.4f}"


def reading_age_minutes(measured_at, now: datetime | None = None) -> float | None:
    """Minutes between a reading's timestamp and now (UTC). None if unknown."""
    if measured_at is None or pd.isna(measured_at):
        return None
    reference = now or datetime.now(timezone.utc)
    timestamp = pd.Timestamp(measured_at)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return (pd.Timestamp(reference) - timestamp).total_seconds() / 60.0


def freshness(flow_m3s, measured_at, now: datetime | None = None) -> str:
    """Classify a reading as Recent / Delayed / Unavailable.

    "Recent" means the reading is at most ``FRESH_MINUTES`` (90) minutes old,
    which comfortably covers Hub'Eau's 5-60 minute publication cycle. Anything
    older is "Delayed"; a missing value is "Unavailable" -- never a zero.
    """
    if flow_m3s is None or pd.isna(flow_m3s):
        return FRESHNESS_UNAVAILABLE
    age = reading_age_minutes(measured_at, now=now)
    if age is None:
        return FRESHNESS_UNAVAILABLE
    return FRESHNESS_RECENT if age <= FRESH_MINUTES else FRESHNESS_DELAYED


def add_freshness_column(frame: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Attach a ``freshness`` column to a station table."""
    if frame.empty:
        return frame.assign(freshness=pd.Series(dtype="object"))
    result = frame.copy()
    result["freshness"] = [
        freshness(row.flow_m3s, row.measured_at, now=now)
        for row in result.itertuples(index=False)
    ]
    return result
