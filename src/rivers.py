"""Loading and styling of the preprocessed river network layers."""

from __future__ import annotations

import json
from pathlib import Path

from src.config import LOD_OVERVIEW, RIVER_BASE_COLOR, RIVER_BASE_OPACITY, Region


class RiversUnavailable(RuntimeError):
    """Raised when a requested river layer has not been generated yet."""


def detail_is_available(region: Region, level_of_detail: str) -> bool:
    """True when the requested level exists in its own right.

    Detail layers are built on demand, so "Detailed" often resolves to the
    overview layer. The UI uses this to say so rather than quietly showing
    something other than what was asked for.
    """
    return region.rivers_path(level_of_detail).exists()


def load_river_geojson(region: Region, level_of_detail: str) -> dict:
    """Read a preprocessed river layer from disk.

    Falls back to the overview layer if a richer one was requested but never
    generated, so a partial checkout still renders a map.
    """
    path = region.rivers_path(level_of_detail)
    if not path.exists() and level_of_detail != LOD_OVERVIEW:
        # Detail layers are built on demand; fall back rather than fail.
        path = region.rivers_path(LOD_OVERVIEW)
    if not path.exists():
        raise RiversUnavailable(
            f"River layer not found for {region.label}. Run: "
            f"python scripts/prepare_rivers.py --department {region.code}"
        )
    return json.loads(Path(path).read_text(encoding="utf-8"))


def river_style(feature: dict) -> dict:
    """Static-ish Leaflet style: wider strokes for wider watercourses."""
    properties = feature.get("properties") or {}
    weight_class = properties.get("weight_class") or 1
    return {
        "color": RIVER_BASE_COLOR,
        "weight": 0.8 + 0.45 * float(weight_class),
        "opacity": RIVER_BASE_OPACITY,
        "fillOpacity": 0,
    }


def count_features(geojson: dict) -> int:
    return len(geojson.get("features") or [])
