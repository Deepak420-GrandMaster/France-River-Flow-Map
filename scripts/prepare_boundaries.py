#!/usr/bin/env python
"""Build the department registry and boundary outlines for metropolitan France.

Downloads the 96 metropolitan department polygons once, simplifies them for
display, and writes:

  data/processed/regions.json              -- registry consumed by src/config.py
  data/processed/boundaries/dep{code}.geojson

The registry is what makes every department selectable in the app. River and
dam layers are optional per department; the app degrades gracefully without
them (live stations come from the API and work everywhere).

    python scripts/prepare_boundaries.py
    python scripts/prepare_boundaries.py --force
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    BOUNDARIES_DIR,
    OUTPUT_CRS,
    PROCESSED_DIR,
    PROJECT_ROOT,
    REGISTRY_PATH,
    WORKING_CRS,
)

#: All metropolitan departments in one open-data file (~3.4 MB).
SOURCE_URL = (
    "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/"
    "departements.geojson"
)

#: Outline simplification, in metres (EPSG:2154). 250 m is invisible at
#: department zoom and cuts the boundary files by roughly 90%.
BOUNDARY_TOLERANCE_M = 250


def log(message: str) -> None:
    print(message, flush=True)


def download_source(cache: Path) -> gpd.GeoDataFrame:
    if not cache.exists():
        import requests

        log(f"Downloading department boundaries from {SOURCE_URL}")
        response = requests.get(SOURCE_URL, timeout=120)
        response.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(response.content)
    return gpd.read_file(cache)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="Rebuild even if the registry exists")
    args = parser.parse_args()

    if REGISTRY_PATH.exists() and not args.force:
        log("Registry already exists. Pass --force to rebuild.")
        return 0

    started = time.time()
    BOUNDARIES_DIR.mkdir(parents=True, exist_ok=True)
    cache = PROCESSED_DIR / "_departements_source.geojson"

    departments = download_source(cache)
    log(f"Departments loaded: {len(departments)}")

    # Simplify in a metric CRS so the tolerance means something.
    projected = departments.to_crs(WORKING_CRS)
    projected["geometry"] = projected.geometry.simplify(
        BOUNDARY_TOLERANCE_M, preserve_topology=True
    )
    simplified = projected.to_crs(OUTPUT_CRS)

    registry = []
    for row in simplified.itertuples(index=False):
        code = str(row.code)
        frame = gpd.GeoDataFrame(
            {"code": [code], "nom": [row.nom]}, geometry=[row.geometry], crs=OUTPUT_CRS
        )
        destination = BOUNDARIES_DIR / f"dep{code}.geojson"
        frame.to_file(destination, driver="GeoJSON", engine="pyogrio", COORDINATE_PRECISION=4)

        minx, miny, maxx, maxy = frame.total_bounds
        registry.append(
            {
                "code": code,
                "name": row.nom,
                # [[lat_min, lon_min], [lat_max, lon_max]] -- the order Leaflet wants.
                "bounds": [[round(miny, 5), round(minx, 5)], [round(maxy, 5), round(maxx, 5)]],
            }
        )

    registry.sort(key=lambda item: item["code"])
    REGISTRY_PATH.write_text(
        json.dumps({"departments": registry}, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    total_mb = sum(p.stat().st_size for p in BOUNDARIES_DIR.glob("*.geojson")) / 1_000_000
    log(f"Wrote {len(registry)} boundaries ({total_mb:.2f} MB) + {REGISTRY_PATH.relative_to(PROJECT_ROOT)}")
    log(f"Done in {time.time() - started:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
