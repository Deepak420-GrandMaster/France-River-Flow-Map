#!/usr/bin/env python
"""Extract dams and reservoirs per department from BD TOPAGE PlanEau.

``PlanEau_FXX`` holds 34,379 French water-body polygons with a ``NaturePE``
class. Three of those classes are what a river-flow map cares about:

  * ``PE - retenue - barrage``  -> dam-impounded reservoir  ("Dam")
  * ``Plan d'eau - réservoir``  -> managed reservoir         ("Reservoir")
  * ``Plan d'eau - retenue``    -> impoundment               ("Reservoir")
  * ``Plan d'eau - lac``        -> natural lake              ("Lake")

Polygons are reduced to points (representative point, guaranteed inside the
shape) plus a surface area, which is all the map needs and keeps the files
tiny. Small ponds are filtered out by area so the layer stays readable.

    python scripts/prepare_dams.py --all
    python scripts/prepare_dams.py --department 34 --force
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    BD_PLANEAU_LAYER,
    BD_PLANEAU_ZIP,
    DAMS_DIR,
    OUTPUT_CRS,
    PROJECT_ROOT,
    WORKING_CRS,
    Region,
    load_regions,
)

#: BD TOPAGE nature -> the category shown in the UI. Anything not listed here
#: (gravel pits, marshes, ponds, glaciers, estuaries) is left out on purpose:
#: they are not flow-regulating structures.
NATURE_CATEGORIES = {
    "PE - retenue - barrage": "Dam",
    "PE - retenue - digue": "Dam",
    "Plan d'eau - réservoir": "Reservoir",
    "PE-réservoir-bassinorage": "Reservoir",
    "PE - réservoir -piscicult": "Reservoir",
    "Plan d'eau - retenue": "Reservoir",
    "Plan d'eau - lac": "Lake",
}

#: Minimum surface area in hectares, per category. Dams matter at any size;
#: there are 25,452 "retenue" polygons nationally, most of them farm ponds, so
#: reservoirs and lakes need a floor to keep the layer legible.
MIN_AREA_HA = {"Dam": 0.0, "Reservoir": 5.0, "Lake": 5.0}

#: At national zoom the department thresholds would put 6,007 markers on one
#: map: unreadable, and slow. Keeping every dam plus only the large standing
#: waters gives 1,250 -- dense enough to show where France stores its water,
#: sparse enough to stay legible.
NATIONAL_MIN_AREA_HA = {"Dam": 0.0, "Reservoir": 50.0, "Lake": 50.0}


def log(message: str) -> None:
    print(message, flush=True)


def resolve_source_archive() -> Path:
    legacy = PROJECT_ROOT / "data:raw" / BD_PLANEAU_ZIP.parent.name / BD_PLANEAU_ZIP.name
    for candidate in (BD_PLANEAU_ZIP, legacy):
        if candidate.exists():
            return candidate
    raise SystemExit(
        f"Source dataset not found. Looked in:\n  {BD_PLANEAU_ZIP}\n  {legacy}\n\n"
        "Download PlanEau_FXX-shp.zip from BD TOPAGE 2024 into "
        "data/raw/BD_Topage_FXX_2024-shp/."
    )


def load_water_bodies() -> gpd.GeoDataFrame:
    source = f"zip://{resolve_source_archive()}!{BD_PLANEAU_LAYER}.shp"
    started = time.time()
    bodies = pyogrio.read_dataframe(source, columns=["TopoOH", "NaturePE", "AltitudeOH"])
    log(f"Water bodies read: {len(bodies):,} in {time.time() - started:.1f}s")

    if bodies.crs is None or bodies.crs.to_epsg() != WORKING_CRS:
        bodies = bodies.to_crs(WORKING_CRS)
    bodies = bodies[bodies.geometry.notna() & ~bodies.geometry.is_empty & bodies.geometry.is_valid]

    bodies["category"] = bodies["NaturePE"].map(NATURE_CATEGORIES)
    bodies = bodies[bodies["category"].notna()].copy()
    bodies["area_ha"] = bodies.geometry.area / 10_000.0

    floor = bodies["category"].map(MIN_AREA_HA).fillna(0.0)
    kept = bodies[bodies["area_ha"] >= floor].copy()
    log(f"  after category + area filter: {len(kept):,}")
    log("  " + ", ".join(f"{k}={v:,}" for k, v in kept['category'].value_counts().items()))

    # representative_point() is always inside the polygon, unlike a centroid on
    # a crescent-shaped reservoir.
    kept["geometry"] = kept.geometry.representative_point()
    return kept


def write_department(bodies: gpd.GeoDataFrame, region: Region) -> Path | None:
    if bodies.empty:
        return None
    output = gpd.GeoDataFrame(
        {
            "name": bodies["TopoOH"].fillna("Unnamed"),
            "category": bodies["category"],
            "area_ha": bodies["area_ha"].round(1),
            "altitude_m": pd.to_numeric(bodies["AltitudeOH"], errors="coerce").round(0),
        },
        geometry=bodies.geometry,
        crs=bodies.crs,
    ).to_crs(OUTPUT_CRS)

    destination = region.dams_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".geojson.tmp")
    output.to_file(temporary, driver="GeoJSON", engine="pyogrio", COORDINATE_PRECISION=5)
    temporary.replace(destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--department", default=None, help="INSEE department code, e.g. 34")
    parser.add_argument("--all", action="store_true", help="Build for every department")
    parser.add_argument("--national", action="store_true", help="Build the France-wide layer")
    parser.add_argument("--force", action="store_true", help="Rebuild even if outputs exist")
    args = parser.parse_args()

    started = time.time()
    regions = load_regions()

    if args.national:
        national = next(r for r in regions.values() if r.is_national)
        if national.dams_path.exists() and not args.force:
            log("National dam layer already exists. Pass --force to rebuild.")
            return 0
        DAMS_DIR.mkdir(parents=True, exist_ok=True)
        bodies = load_water_bodies()
        floor = bodies["category"].map(NATIONAL_MIN_AREA_HA).fillna(0.0)
        significant = bodies[bodies["area_ha"] >= floor].copy()
        log(f"  national selection: {len(significant):,} "
            + ", ".join(f"{k}={v:,}" for k, v in significant["category"].value_counts().items()))
        path = write_department(significant, national)
        if path:
            log(f"Wrote {path.relative_to(PROJECT_ROOT)} "
                f"({path.stat().st_size / 1_000_000:.2f} MB) in {time.time() - started:.1f}s.")
        return 0

    targets = (
        list(regions.values())
        if args.all
        else [r for r in regions.values() if r.code == (args.department or "34")]
    )
    if not targets:
        raise SystemExit(f"Unknown department '{args.department}'.")

    DAMS_DIR.mkdir(parents=True, exist_ok=True)
    bodies = load_water_bodies()

    boundaries = []
    for region in targets:
        if region.boundary_path.exists():
            frame = gpd.read_file(region.boundary_path).to_crs(WORKING_CRS)
            frame["dep_code"] = region.code
            boundaries.append(frame[["dep_code", "geometry"]])
    if not boundaries:
        raise SystemExit("No boundaries found. Run: python scripts/prepare_boundaries.py")

    all_boundaries = gpd.GeoDataFrame(pd.concat(boundaries, ignore_index=True), crs=WORKING_CRS)
    joined = bodies.sjoin(all_boundaries, predicate="within")
    joined = joined.drop(columns=[c for c in joined.columns if c.startswith("index_right")])

    written = 0
    for region in targets:
        if region.dams_path.exists() and not args.force:
            continue
        subset = joined[joined["dep_code"] == region.code]
        if write_department(subset.drop(columns=["dep_code"]), region):
            written += 1

    total_mb = sum(p.stat().st_size for p in DAMS_DIR.glob("*.geojson")) / 1_000_000
    log(f"\nWrote {written} department file(s). "
        f"{len(list(DAMS_DIR.glob('*.geojson')))} files, {total_mb:.2f} MB total.")
    log(f"Done in {time.time() - started:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
