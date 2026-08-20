"""Central configuration: paths, regions, cartography and thresholds.

Everything a contributor is likely to tune lives here so the Streamlit app and
the preprocessing scripts never disagree about a constant.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# --------------------------------------------------------------------------
# Paths -- resolved from this file so the app works from any working
# directory (important on Streamlit Community Cloud).
# --------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"              # never committed -- see .gitignore
PROCESSED_DIR = DATA_DIR / "processed"  # small, committed, used at runtime

BOUNDARIES_DIR = PROCESSED_DIR / "boundaries"
RIVERS_DIR = PROCESSED_DIR / "rivers"
DAMS_DIR = PROCESSED_DIR / "dams"
REGISTRY_PATH = PROCESSED_DIR / "regions.json"

# BD TOPAGE 2024 national datasets (local-only, hundreds of MB).
BD_TOPAGE_DIR = RAW_DIR / "BD_Topage_FXX_2024-shp"
BD_TOPAGE_ZIP = BD_TOPAGE_DIR / "TronconHydrographique_FXX-shp.zip"
BD_TOPAGE_LAYER = "TronconHydrographique_FXX"
BD_PLANEAU_ZIP = BD_TOPAGE_DIR / "PlanEau_FXX-shp.zip"
BD_PLANEAU_LAYER = "PlanEau_FXX"

# --------------------------------------------------------------------------
# Coordinate reference systems
# --------------------------------------------------------------------------
# BD TOPAGE ships in Lambert-93. All length and simplification maths must run
# in a projected CRS so tolerances are expressed in real metres.
WORKING_CRS = 2154   # RGF93 / Lambert-93 (metres)
OUTPUT_CRS = 4326    # WGS 84 (degrees) -- what Leaflet/Folium expects

# --------------------------------------------------------------------------
# Levels of detail
# --------------------------------------------------------------------------
# Folium serialises every feature into the page, so feature count -- not just
# file size -- drives browser performance. "overview" is the default and is
# the only level generated for every department.
LOD_OVERVIEW = "overview"
LOD_DETAIL = "detail"
LOD_HIDDEN = "hidden"
LEVELS_OF_DETAIL = {
    LOD_OVERVIEW: "Overview",
    LOD_DETAIL: "Detailed",
    LOD_HIDDEN: "Hide rivers",
}


# --------------------------------------------------------------------------
# Safe path construction
# --------------------------------------------------------------------------
#: Department codes are two digits, or 2A/2B for Corsica, or the national
#: pseudo-code. Anything else is rejected before it can reach a filename or an
#: API query string.
DEPARTMENT_CODE_PATTERN = re.compile(r"\A(?:\d{2}|2[AB]|FR)\Z")


def validate_department_code(code: str) -> str:
    """Return ``code`` if it is a well-formed department code, else raise.

    Department codes flow into both filesystem paths and Hub'Eau query
    strings, so they are validated at the boundary rather than trusted.
    """
    if not isinstance(code, str) or not DEPARTMENT_CODE_PATTERN.match(code):
        raise ValueError(f"Invalid department code: {code!r}")
    return code


def processed_path(*parts: str) -> Path:
    """Build a path under ``data/processed`` and refuse to escape it.

    Defence in depth: every caller today passes a validated code, but a future
    one might forward a request parameter, and ``../`` in a filename would
    otherwise read arbitrary files off the deployment host.
    """
    root = PROCESSED_DIR.resolve()
    candidate = (root / Path(*parts)).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"Refusing to read outside the data directory: {candidate}")
    return candidate


# --------------------------------------------------------------------------
# Regions
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Region:
    """One French department.

    Live gauging stations come from Hub'Eau and work for every department, so
    a region is always selectable. River and dam layers are optional local
    files; the app says so rather than failing when one is absent.
    """

    code: str                      # INSEE department code, e.g. "34"
    name: str                      # e.g. "Hérault"
    bounds: list[list[float]]      # [[lat_min, lon_min], [lat_max, lon_max]]

    @property
    def is_national(self) -> bool:
        """True for the whole-country landing view.

        Live discharge is fetched per department; fetching it for every
        gauging station in France would mean dozens of API calls per page
        load, so the national scope shows the river network and invites the
        reader to pick a department for live readings.
        """
        return self.code == NATIONAL_CODE

    @property
    def key(self) -> str:
        return NATIONAL_KEY if self.is_national else f"dep{self.code}"

    @property
    def label(self) -> str:
        return self.name if self.is_national else f"{self.name} ({self.code})"

    @property
    def center(self) -> tuple[float, float]:
        (lat_min, lon_min), (lat_max, lon_max) = self.bounds
        return ((lat_min + lat_max) / 2, (lon_min + lon_max) / 2)

    @property
    def boundary_path(self) -> Path:
        name = "france.geojson" if self.is_national else f"dep{validate_department_code(self.code)}.geojson"
        return processed_path("boundaries", name)

    @property
    def dams_path(self) -> Path:
        name = "france.geojson" if self.is_national else f"dep{validate_department_code(self.code)}.geojson"
        return processed_path("dams", name)

    def rivers_path(self, level_of_detail: str) -> Path:
        if self.is_national:
            return processed_path("rivers", "france_overview.geojson")
        if level_of_detail not in LEVELS_OF_DETAIL:
            raise ValueError(f"Unknown level of detail: {level_of_detail!r}")
        code = validate_department_code(self.code)
        return processed_path("rivers", f"dep{code}_{level_of_detail}.geojson")

    @property
    def has_rivers(self) -> bool:
        return self.rivers_path(LOD_OVERVIEW).exists()

    @property
    def has_dams(self) -> bool:
        return self.dams_path.exists()


#: The whole-country landing view.
NATIONAL_CODE = "FR"
NATIONAL_KEY = "france"
NATIONAL_NAME = "France — all rivers"
#: Metropolitan France, including Corsica.
NATIONAL_BOUNDS = [[41.33, -5.15], [51.10, 9.57]]

#: Hérault is the pilot department.
DEFAULT_DEPARTMENT_CODE = "34"
#: ...but the app opens on the whole country.
DEFAULT_REGION_KEY = NATIONAL_KEY

#: Fallback used only when the registry is missing entirely, so the app can
#: still start on a partial checkout.
_FALLBACK_REGION = Region(
    code=DEFAULT_DEPARTMENT_CODE,
    name="Hérault",
    bounds=[[43.21281, 2.5407], [43.97275, 4.19449]],
)


NATIONAL_REGION = Region(code=NATIONAL_CODE, name=NATIONAL_NAME, bounds=NATIONAL_BOUNDS)


@lru_cache(maxsize=1)
def load_regions() -> dict[str, Region]:
    """Every metropolitan department, keyed by ``dep{code}``.

    Built by ``scripts/prepare_boundaries.py``. Ordered by department code so
    the sidebar reads like the official list.
    """
    base = {NATIONAL_REGION.key: NATIONAL_REGION}
    if not REGISTRY_PATH.exists():
        return {**base, _FALLBACK_REGION.key: _FALLBACK_REGION}

    try:
        payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        entries = payload["departments"]
    except (OSError, ValueError, KeyError):
        return {**base, _FALLBACK_REGION.key: _FALLBACK_REGION}

    regions: dict[str, Region] = dict(base)
    for entry in entries:
        region = Region(code=str(entry["code"]), name=entry["name"], bounds=entry["bounds"])
        regions[region.key] = region
    return regions


def get_region(key: str | None) -> Region:
    """Look up a region, falling back to the default department."""
    regions = load_regions()
    if key and key in regions:
        return regions[key]
    return regions.get(DEFAULT_REGION_KEY) or next(iter(regions.values()))


# --------------------------------------------------------------------------
# Reading freshness
# --------------------------------------------------------------------------
# Hub'Eau publishes real-time discharge roughly every 5-60 minutes, and some
# stations lag further. A reading up to FRESH_MINUTES old is treated as
# current; older but still inside the API lookback window is "Delayed"; no
# reading at all is "Unavailable". These labels are shown verbatim in the UI.
FRESH_MINUTES = 90
FRESHNESS_RECENT = "Recent"
FRESHNESS_DELAYED = "Delayed"
FRESHNESS_UNAVAILABLE = "Unavailable"

# --------------------------------------------------------------------------
# Cartography
# --------------------------------------------------------------------------
BASEMAP_TILES = "CartoDB positron"  # light, professional, no API key

#: Rivers are drawn as two stacked strokes: a soft static base plus an
#: animated dashed overlay that reads as flowing water on a light basemap.
RIVER_BASE_COLOR = "#a8cde4"
RIVER_FLOW_COLOR = "#1c6fa8"
RIVER_BASE_OPACITY = 0.55
RIVER_FLOW_OPACITY = 0.9

#: Animation speed, expressed as the CSS animation duration in seconds.
#: Lower duration = faster apparent current. One period moves each dash four
#: full cycles (96 px), so this range spans roughly 24 px/s to 240 px/s --
#: slow enough to study, fast enough to look like a river in spate.
FLOW_SPEED_MIN, FLOW_SPEED_MAX, FLOW_SPEED_DEFAULT = 0.4, 4.0, 1.6

DAM_COLOR = "#7b5ea7"
RESERVOIR_COLOR = "#4aa3c7"
LABEL_COLOR = "#42627a"

# Flow classes drive both the marker colours and the legend. Upper bound is
# exclusive; the last class is open-ended.
FLOW_CLASSES: list[tuple[float | None, str, str]] = [
    (1.0, "#2c7fb8", "Under 1 m³/s"),
    (10.0, "#41ab5d", "1 – 10 m³/s"),
    (100.0, "#f0a202", "10 – 100 m³/s"),
    (None, "#d7301f", "Over 100 m³/s"),
]
NO_DATA_COLOR = "#9e9e9e"
NO_DATA_LABEL = "No recent reading"

# --------------------------------------------------------------------------
# Flow versus seasonal normal
# --------------------------------------------------------------------------
# "Normal" is the median monthly mean discharge for the same calendar month
# across all published years (Hub'Eau QmM). Ratios below are current / normal.
NORMAL_CLASSES: list[tuple[float | None, str, str]] = [
    (0.5, "#b2182b", "Much below normal"),
    (0.85, "#ef8a62", "Below normal"),
    (1.15, "#8db97f", "Near normal"),
    (2.0, "#67a9cf", "Above normal"),
    (None, "#2166ac", "Much above normal"),
]
NORMAL_UNKNOWN_COLOR = "#c8ccd1"
NORMAL_UNKNOWN_LABEL = "No reference data"

ATTRIBUTION = "Sources: Hub'Eau Hydrométrie, BD TOPAGE, OpenStreetMap/CARTO"


def flow_color(flow_m3s: float | None) -> str:
    """Return the marker colour for a discharge value in m³/s."""
    if flow_m3s is None:
        return NO_DATA_COLOR
    for upper, color, _ in FLOW_CLASSES:
        if upper is None or flow_m3s < upper:
            return color
    return NO_DATA_COLOR


def normal_ratio_color(ratio: float | None) -> str:
    """Colour for a current/normal discharge ratio."""
    if ratio is None:
        return NORMAL_UNKNOWN_COLOR
    for upper, color, _ in NORMAL_CLASSES:
        if upper is None or ratio < upper:
            return color
    return NORMAL_UNKNOWN_COLOR


def normal_ratio_label(ratio: float | None) -> str:
    """Human label for a current/normal discharge ratio."""
    if ratio is None:
        return NORMAL_UNKNOWN_LABEL
    for upper, _, label in NORMAL_CLASSES:
        if upper is None or ratio < upper:
            return label
    return NORMAL_UNKNOWN_LABEL
