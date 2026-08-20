#!/usr/bin/env python
"""Turn the national BD TOPAGE river network into lightweight per-department layers.

Why this exists
---------------
BD TOPAGE ships 3,013,824 river segments for metropolitan France. A naive
bounding-box extraction around one department yields ~135,000 segments and a
132 MB GeoJSON: Folium serialises every feature into the page, so the browser
stalls and the map is unreadable. This script produces layers small enough to
animate smoothly while still looking like a real river network.

The reduction happens in four stages, in this order:

1. **Spatial filter** -- either a driver-level bounding box (single department)
   or one national read joined against all 96 department polygons (``--all``).
2. **Attribute filter** -- the overview keeps only BD TOPAGE's "main network"
   flag (``ReseauPrin``), the cartographic skeleton of each basin.
3. **Dissolve + merge** -- contiguous segments of the same watercourse become a
   single feature. The biggest win, because *feature count* (not byte size) is
   what slows Folium down.
4. **Length filter + simplification** -- both in metres, which is only correct
   in a projected CRS, so all geometry maths runs in EPSG:2154.

Usage
-----
    python scripts/prepare_rivers.py --all              # overview, every department
    python scripts/prepare_rivers.py --department 34    # both levels, one department
    python scripts/prepare_rivers.py --department 34 --level detail --force

``--all`` builds the *overview* level only: detail layers for all 96
departments would add roughly 200 MB to the repository. Build detail on demand
for the departments you care about; the app falls back to overview elsewhere.

Re-running is safe: outputs are written to a temporary file then moved into
place, and existing files are skipped unless ``--force`` is passed.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely
from shapely import force_2d
from shapely.ops import linemerge

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    BD_TOPAGE_LAYER,
    BD_TOPAGE_ZIP,
    BOUNDARIES_DIR,
    LOD_DETAIL,
    LOD_OVERVIEW,
    OUTPUT_CRS,
    PROJECT_ROOT,
    RIVERS_DIR,
    WORKING_CRS,
    Region,
    load_regions,
)

# --------------------------------------------------------------------------
# Tuning constants
# --------------------------------------------------------------------------
# MIN_LENGTH_M -- drops tributary stubs shorter than this (metres, measured
#   *after* merging, so a long river made of short segments is never dropped).
#   Lower it for a denser network; raise it for a cleaner, faster map.
# SIMPLIFY_TOLERANCE_M -- Douglas-Peucker tolerance in metres with
#   preserve_topology=True: roughly "how far a drawn line may stray from the
#   true course". 60 m is invisible at department zoom; 20 m holds up when
#   zoomed into a town. Raising it shrinks the file roughly linearly.
# MAIN_NETWORK_ONLY -- BD TOPAGE's ReseauPrin flag marks the principal
#   hydrographic network: an excellent proxy for "rivers a reader expects".


@dataclass(frozen=True)
class LodProfile:
    name: str
    main_network_only: bool
    min_length_m: int
    simplify_tolerance_m: int


LOD_PROFILES: dict[str, LodProfile] = {
    LOD_OVERVIEW: LodProfile(LOD_OVERVIEW, True, 2000, 60),
    LOD_DETAIL: LodProfile(LOD_DETAIL, False, 500, 20),
}

#: The whole-country landing view. Only watercourses at least this long are
#: kept: at national zoom anything shorter is a pixel, and the file has to
#: stay small enough to ship to a browser in one go. Measured alternatives:
#: >=40 km -> 704 features / 1.0 MB (too sparse); >=25 km -> 1,511 / 1.6 MB;
#: >=15 km -> 3,272 / 2.7 MB, which reads as a real river network.
NATIONAL_PROFILE = LodProfile("national", True, 15_000, 200)

SOURCE_COLUMNS = ["TopoOH", "Persistanc", "ReseauPrin", "ClasseLarg", "CdCoursEau"]

# BD TOPAGE width classes -> a 1..4 rendering weight used by the map styling.
WIDTH_CLASS_WEIGHT = {"0_5": 1, "5_15": 2, "15_50": 3, "50": 4}


def log(message: str) -> None:
    print(message, flush=True)


def mb(path: Path) -> float:
    return path.stat().st_size / 1_000_000


def resolve_source_archive() -> Path:
    """Locate the BD TOPAGE archive, tolerating the legacy ``data:raw`` folder.

    Early versions of this project stored the download in a directory literally
    named ``data:raw`` (with a colon). The standard location is ``data/raw``;
    the legacy path is still accepted so an un-migrated checkout keeps working.
    """
    legacy = PROJECT_ROOT / "data:raw" / BD_TOPAGE_ZIP.parent.name / BD_TOPAGE_ZIP.name
    for candidate in (BD_TOPAGE_ZIP, legacy):
        if candidate.exists():
            if candidate == legacy:
                log(f"  ! using legacy path {candidate} -- move it to {BD_TOPAGE_ZIP.parent}/")
            return candidate

    raise SystemExit(
        f"Source dataset not found. Looked in:\n  {BD_TOPAGE_ZIP}\n  {legacy}\n\n"
        "Download TronconHydrographique_FXX-shp.zip from BD TOPAGE 2024 and place\n"
        "it in data/raw/BD_Topage_FXX_2024-shp/ (see README.md > Preprocessing)."
    )


def load_boundary(region: Region) -> gpd.GeoDataFrame:
    """Department polygon in the working CRS."""
    if not region.boundary_path.exists():
        raise SystemExit(
            f"Boundary missing for {region.label}.\n"
            "Run: python scripts/prepare_boundaries.py"
        )
    return gpd.read_file(region.boundary_path).to_crs(WORKING_CRS)


def clean_segments(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Force 2D and drop null / empty / invalid geometries."""
    if segments.crs is None:
        raise SystemExit("Source dataset has no CRS; cannot continue safely.")
    if segments.crs.to_epsg() != WORKING_CRS:
        segments = segments.to_crs(WORKING_CRS)

    # BD TOPAGE geometries are LineString Z. The Z ordinate is unused by
    # Leaflet and inflates the GeoJSON by roughly a third.
    segments = segments.copy()
    segments["geometry"] = force_2d(segments.geometry)
    before = len(segments)
    segments = segments[
        segments.geometry.notna() & ~segments.geometry.is_empty & segments.geometry.is_valid
    ]
    if before != len(segments):
        log(f"  dropped {before - len(segments):,} null/empty/invalid geometries")
    return segments


def safe_linemerge(geometry):
    """``linemerge`` that tolerates every geometry shapely can hand us.

    ``union_all()`` returns a bare LineString when a department contributes a
    single unnamed segment, and ``linemerge`` rejects that input. Empty and
    collection results are handled here too so one odd department cannot abort
    a 96-department run.
    """
    if geometry is None or geometry.is_empty:
        return geometry
    if geometry.geom_type == "LineString":
        return geometry
    try:
        return linemerge(geometry)
    except (ValueError, TypeError):
        return geometry


def dissolve_watercourses(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Merge segments into whole watercourses.

    Named watercourses are dissolved on their BD TOPAGE code. Segments without
    a watercourse code (~69% of a typical extract) are merged as one network
    and then exploded, so contiguous chains become single features while
    unrelated stubs stay separate.
    """
    parts: list[gpd.GeoDataFrame] = []

    named = segments[segments["CdCoursEau"].notna()]
    if len(named):
        merged = named.dissolve(
            by="CdCoursEau",
            aggfunc={"TopoOH": "first", "ClasseLarg": "first", "Persistanc": "first"},
        ).reset_index()
        # dissolve() yields MultiLineStrings; stitch contiguous pieces together.
        merged["geometry"] = merged.geometry.apply(safe_linemerge)
        parts.append(merged)

    unnamed = segments[segments["CdCoursEau"].isna()]
    if len(unnamed):
        network = safe_linemerge(unnamed.geometry.union_all())
        exploded = (
            gpd.GeoDataFrame(geometry=gpd.GeoSeries([network], crs=segments.crs))
            .explode(index_parts=False)
            .reset_index(drop=True)
        )
        exploded = exploded[exploded.geometry.geom_type == "LineString"]
        exploded["CdCoursEau"] = None
        exploded["TopoOH"] = None
        # Width and persistence cannot be attributed reliably after an unnamed
        # merge, so they are left unset rather than guessed.
        exploded["ClasseLarg"] = None
        exploded["Persistanc"] = None
        parts.append(exploded)

    if not parts:
        return segments.iloc[0:0].copy()

    combined = pd.concat(parts, ignore_index=True)
    return gpd.GeoDataFrame(combined, geometry="geometry", crs=segments.crs)


def build_level(
    segments: gpd.GeoDataFrame, profile: LodProfile, region: Region, verbose: bool = True
) -> Path | None:
    """Run the reduction for one level of detail and write the GeoJSON."""
    started = time.time()
    if verbose:
        log(f"\n[{region.label} / {profile.name}] main_only={profile.main_network_only} "
            f"min_length={profile.min_length_m} m tolerance={profile.simplify_tolerance_m} m")

    selected = (
        segments[segments["ReseauPrin"] == 1] if profile.main_network_only else segments
    ).copy()
    if selected.empty:
        if verbose:
            log("  no segments for this department -- skipped")
        return None
    if verbose:
        log(f"  after attribute filter : {len(selected):,}")

    merged = dissolve_watercourses(selected)
    if verbose:
        log(f"  after dissolve/merge   : {len(merged):,}")

    merged["length_m"] = merged.geometry.length
    merged = merged[merged["length_m"] >= profile.min_length_m].copy()
    if merged.empty:
        if verbose:
            log("  nothing survived the length filter -- skipped")
        return None
    if verbose:
        log(f"  after length filter    : {len(merged):,}")

    vertices_before = int(shapely.get_num_coordinates(merged.geometry.values).sum())
    merged["geometry"] = merged.geometry.simplify(
        profile.simplify_tolerance_m, preserve_topology=True
    )
    merged = merged[~merged.geometry.is_empty & merged.geometry.notna()]
    vertices_after = int(shapely.get_num_coordinates(merged.geometry.values).sum())
    if verbose:
        log(f"  after simplification   : {len(merged):,} features, "
            f"{vertices_before:,} -> {vertices_after:,} vertices")

    output = gpd.GeoDataFrame(
        {
            "name": merged["TopoOH"],
            "weight_class": merged["ClasseLarg"].map(WIDTH_CLASS_WEIGHT).fillna(1).astype(int),
            "permanent": (merged["Persistanc"] == "permanent"),
            "length_km": (merged["length_m"] / 1000).round(1),
        },
        geometry=merged.geometry,
        crs=merged.crs,
    ).to_crs(OUTPUT_CRS)

    destination = region.rivers_path(profile.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".geojson.tmp")
    # COORDINATE_PRECISION=5 -> ~1 m on the ground, and a much smaller file.
    output.to_file(temporary, driver="GeoJSON", engine="pyogrio", COORDINATE_PRECISION=5)
    temporary.replace(destination)

    if verbose:
        log(f"  wrote {destination.relative_to(PROJECT_ROOT)} -- {len(output):,} features, "
            f"{mb(destination):.2f} MB ({time.time() - started:.1f}s)")
    return destination


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------
def build_single_department(region: Region, levels: list[str]) -> list[Path]:
    """Bounding-box read for one department -- fast when you only need one."""
    boundary = load_boundary(region)
    source = f"zip://{resolve_source_archive()}!{BD_TOPAGE_LAYER}.shp"
    total_features = int(pyogrio.read_info(source)["features"])

    started = time.time()
    # Bounding-box pushdown: the driver skips features outside the box, so we
    # never materialise the 3M-feature national dataset.
    segments = pyogrio.read_dataframe(
        source, bbox=tuple(boundary.total_bounds), columns=SOURCE_COLUMNS
    )
    log(f"  bbox read: {len(segments):,} features in {time.time() - started:.1f}s")

    segments = clean_segments(segments)
    refined = segments.sjoin(boundary[["geometry"]], predicate="intersects")
    refined = refined.drop(columns=[c for c in refined.columns if c.startswith("index_right")])
    # A multi-part boundary can match the same segment more than once. Dedupe
    # on the *source row index* -- never on attribute values, since thousands
    # of distinct segments legitimately share the same attributes.
    refined = refined[~refined.index.duplicated(keep="first")].reset_index(drop=True)

    log(f"\nSource features (national) : {total_features:,}")
    log(f"After department filter    : {len(refined):,}")

    written = [build_level(refined, LOD_PROFILES[level], region) for level in levels]
    return [path for path in written if path]


def build_all_departments(regions: dict[str, Region], force: bool) -> list[Path]:
    """One national read, then every department in turn.

    96 separate bounding-box reads would each rescan the 690 MB shapefile
    (~13 s apiece, over 20 minutes total). Reading once costs ~25 s and about
    2 GB of RAM, then the per-department work is pure in-memory geometry.
    """
    source = f"zip://{resolve_source_archive()}!{BD_TOPAGE_LAYER}.shp"
    started = time.time()
    log("Reading the national river network (one pass)...")
    national = pyogrio.read_dataframe(source, columns=SOURCE_COLUMNS)
    log(f"  {len(national):,} features in {time.time() - started:.0f}s")

    national = clean_segments(national)
    # --all builds the overview only, so drop everything else immediately:
    # this cuts memory roughly in half before the spatial join.
    national = national[national["ReseauPrin"] == 1]
    log(f"  main network: {len(national):,} features")

    boundaries = []
    for region in regions.values():
        if region.boundary_path.exists():
            frame = gpd.read_file(region.boundary_path).to_crs(WORKING_CRS)
            frame["dep_code"] = region.code
            boundaries.append(frame[["dep_code", "geometry"]])
    if not boundaries:
        raise SystemExit("No boundaries found. Run: python scripts/prepare_boundaries.py")

    all_boundaries = gpd.GeoDataFrame(pd.concat(boundaries, ignore_index=True), crs=WORKING_CRS)
    log(f"  joining against {len(all_boundaries)} department polygons...")
    started = time.time()
    joined = national.sjoin(all_boundaries, predicate="intersects")
    joined = joined.drop(columns=[c for c in joined.columns if c.startswith("index_right")])
    log(f"  spatial join produced {len(joined):,} rows in {time.time() - started:.0f}s")
    del national

    written: list[Path] = []
    profile = LOD_PROFILES[LOD_OVERVIEW]
    total = len(regions)
    for index, region in enumerate(regions.values(), start=1):
        destination = region.rivers_path(LOD_OVERVIEW)
        if destination.exists() and not force:
            continue
        subset = joined[joined["dep_code"] == region.code]
        if subset.empty:
            log(f"[{index:>2}/{total}] {region.label:<34} no segments")
            continue
        try:
            path = build_level(subset.drop(columns=["dep_code"]), profile, region, verbose=False)
        except Exception as exc:
            log(f"[{index:>2}/{total}] {region.label:<34} FAILED: {type(exc).__name__}: {exc}")
            continue
        if path:
            written.append(path)
            log(f"[{index:>2}/{total}] {region.label:<34} "
                f"{len(subset):>7,} segs -> {mb(path):>5.2f} MB")
    return written


def build_national(force: bool) -> list[Path]:
    """One France-wide river layer plus the national outline for the mask."""
    destination = RIVERS_DIR / "france_overview.geojson"
    outline = BOUNDARIES_DIR / "france.geojson"
    if destination.exists() and outline.exists() and not force:
        log("National layer already exists. Pass --force to rebuild.")
        return []

    source = f"zip://{resolve_source_archive()}!{BD_TOPAGE_LAYER}.shp"
    started = time.time()
    log("Reading the national river network (one pass)...")
    national = pyogrio.read_dataframe(source, columns=SOURCE_COLUMNS)
    log(f"  {len(national):,} features in {time.time() - started:.0f}s")

    national = clean_segments(national)
    national = national[national["ReseauPrin"] == 1]
    log(f"  main network: {len(national):,} features")

    merged = dissolve_watercourses(national)
    log(f"  dissolved to {len(merged):,} watercourses")
    del national

    merged["length_m"] = merged.geometry.length
    merged = merged[merged["length_m"] >= NATIONAL_PROFILE.min_length_m].copy()
    log(f"  at least {NATIONAL_PROFILE.min_length_m / 1000:.0f} km: {len(merged):,}")
    merged["geometry"] = merged.geometry.simplify(
        NATIONAL_PROFILE.simplify_tolerance_m, preserve_topology=True
    )
    merged = merged[~merged.geometry.is_empty & merged.geometry.notna()]

    output = gpd.GeoDataFrame(
        {
            "name": merged["TopoOH"],
            # Long rivers read better slightly heavier at national zoom.
            "weight_class": merged["ClasseLarg"].map(WIDTH_CLASS_WEIGHT).fillna(2).astype(int),
            "permanent": (merged["Persistanc"] == "permanent"),
            "length_km": (merged["length_m"] / 1000).round(0),
        },
        geometry=merged.geometry, crs=merged.crs,
    ).to_crs(OUTPUT_CRS)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".geojson.tmp")
    output.to_file(temporary, driver="GeoJSON", engine="pyogrio", COORDINATE_PRECISION=4)
    temporary.replace(destination)
    log(f"  wrote {destination.relative_to(PROJECT_ROOT)} -- {len(output):,} features, "
        f"{mb(destination):.2f} MB")

    # National outline = the union of every department, used for the mask.
    parts = [
        gpd.read_file(path) for path in sorted(BOUNDARIES_DIR.glob("dep*.geojson"))
    ]
    if parts:
        combined = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=OUTPUT_CRS)
        dissolved = gpd.GeoDataFrame(
            {"code": ["FR"], "nom": ["France"]},
            geometry=[combined.to_crs(WORKING_CRS).geometry.union_all().buffer(0)],
            crs=WORKING_CRS,
        ).to_crs(OUTPUT_CRS)
        dissolved.to_file(outline, driver="GeoJSON", engine="pyogrio", COORDINATE_PRECISION=4)
        log(f"  wrote {outline.relative_to(PROJECT_ROOT)} -- {mb(outline):.2f} MB")

    return [destination]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--department", default=None, help="INSEE department code, e.g. 34")
    parser.add_argument("--all", action="store_true", help="Build the overview layer for every department")
    parser.add_argument("--national", action="store_true", help="Build the France-wide landing layer")
    parser.add_argument(
        "--level", choices=[LOD_OVERVIEW, LOD_DETAIL, "all"], default="all",
        help="Level(s) of detail for a single department (default: all)",
    )
    parser.add_argument("--force", action="store_true", help="Rebuild even if outputs already exist")
    return parser.parse_args()


def main() -> int:
    overall_started = time.time()
    args = parse_args()
    regions = load_regions()
    RIVERS_DIR.mkdir(parents=True, exist_ok=True)

    if args.national:
        written = build_national(force=args.force)
    elif args.all:
        written = build_all_departments(regions, force=args.force)
    else:
        code = args.department or "34"
        region = next((r for r in regions.values() if r.code == code), None)
        if region is None:
            raise SystemExit(
                f"Unknown department '{code}'. Run scripts/prepare_boundaries.py first."
            )
        levels = list(LOD_PROFILES) if args.level == "all" else [args.level]
        pending = [lvl for lvl in levels if args.force or not region.rivers_path(lvl).exists()]
        if not pending:
            log("All requested layers already exist. Pass --force to rebuild.")
            return 0
        log(f"Region: {region.label}")
        written = build_single_department(region, pending)

    log(f"\nDone in {time.time() - overall_started:.0f}s. Wrote {len(written)} layer(s).")
    total_mb = sum(mb(p) for p in RIVERS_DIR.glob("*.geojson"))
    log(f"River layers on disk: {len(list(RIVERS_DIR.glob('*.geojson')))} files, {total_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
