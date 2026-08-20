"""Last-known-good snapshots of live data, persisted to disk.

Hub'Eau is a free public service: it goes down, and it throttles bursts hard
enough that a client can be shut out for many minutes. Without a fallback the
dashboard collapses to zeros during those windows, which is both useless and
misleading about the state of French rivers.

Every successful fetch is written here. When a later fetch fails, the app
shows the stored readings **clearly labelled with the time they were taken**.
That is cached data with full provenance, not invented data: the freshness
column still classifies each reading from its own measurement timestamp, so an
old value reads as "Delayed" or "Unavailable", never as current.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

CACHE_DIR = DATA_DIR / "cache"
#: Beyond this, a snapshot is too old to be worth showing at all.
MAX_SNAPSHOT_AGE_HOURS = 48


def _path(kind: str, department_code: str) -> Path:
    return CACHE_DIR / f"{kind}-{department_code}.json"


def save(kind: str, department_code: str, frame: pd.DataFrame) -> None:
    """Persist a successful fetch. Failures here are never fatal."""
    if frame is None or frame.empty:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "rows": json.loads(frame.to_json(orient="records", date_format="iso")),
        }
        temporary = _path(kind, department_code).with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(_path(kind, department_code))
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Could not write %s snapshot for %s: %s", kind, department_code, exc)


def load(kind: str, department_code: str) -> tuple[pd.DataFrame | None, datetime | None]:
    """Return ``(frame, saved_at)`` for a stored snapshot, or ``(None, None)``."""
    path = _path(kind, department_code)
    if not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        saved_at = pd.Timestamp(payload["saved_at"]).to_pydatetime()
        if saved_at.tzinfo is None:
            saved_at = saved_at.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - saved_at).total_seconds() / 3600
        if age_hours > MAX_SNAPSHOT_AGE_HOURS:
            return None, None
        frame = pd.DataFrame(payload["rows"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Could not read %s snapshot for %s: %s", kind, department_code, exc)
        return None, None

    if frame.empty:
        return None, None
    for column in ("measured_at",):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
    return frame, saved_at
