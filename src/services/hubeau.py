"""Client for the public Hub'Eau Hydrométrie API (v2).

Documentation: https://hubeau.eaufrance.fr/page/api-hydrometrie
No API key, no account, no quota registration -- but the service does throttle
bursts, so every call goes through a retrying session and callers are expected
to cache results.

Verified API behaviour (probed 2026-08-20, see scripts/check_hubeau_api.py):

* ``/referentiel/stations`` filters on ``code_departement``.
* ``/observations_tr`` filters on **``code_entite``**, *not* ``code_station``.
  Passing ``code_station`` silently returns unfiltered results.
* ``code_entite`` accepts a comma-separated list, which lets us fetch every
  station in one request instead of one request per station.
* Responses use HTTP **206** for partial/paginated content. That is a success
  for this API, so 200 and 206 are both accepted.
* Discharge (``grandeur_hydro=Q``) is returned in **litres per second**;
  divide by 1000 for m³/s.
* Observation rows *do* carry ``code_station``, but the caller-supplied code is
  kept as a fallback so a missing field can never mislabel a station.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import validate_department_code

logger = logging.getLogger(__name__)

BASE_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie"
STATIONS_ENDPOINT = f"{BASE_URL}/referentiel/stations"
OBSERVATIONS_ENDPOINT = f"{BASE_URL}/observations_tr"
#: "Elaborated" observations: validated aggregates rather than raw real-time.
OBS_ELAB_ENDPOINT = f"{BASE_URL}/obs_elab"
#: Monthly mean discharge. Verified valid; "QmM" is the only monthly code the
#: API accepts (QM / QmnM are rejected). Daily means are "QmnJ".
GRANDEUR_MONTHLY_MEAN = "QmM"

#: HTTP statuses Hub'Eau uses for a successful payload. 206 = partial content.
SUCCESS_STATUSES = frozenset({200, 206})

#: Hub'Eau returns discharge in L/s.
LITRES_PER_CUBIC_METRE = 1000.0

#: Conservative caps. The API rejects or resets very large requests, and we do
#: not want to hammer a free public service.
MAX_PAGE_SIZE = 1000
MAX_CODES_PER_REQUEST = 50
#: (connect, read) seconds. Measured against the live service: when Hub'Eau is
#: under load it completes the TCP and TLS handshake instantly but then takes
#: **9-10 seconds** to produce a response, and sometimes drops the connection
#: at the 10 s mark. A tight connect timeout turns those slow-but-successful
#: calls into hard failures, so both budgets are deliberately generous.
DEFAULT_TIMEOUT = (15, 60)

#: How far back to look for a "latest" reading. Measured trade-off for the 46
#: Hérault stations: 2 h -> 29 stations in 1 page (~1.0 s); 3 h -> 29 stations
#: in 1 page (~1.9 s); 6 h -> 30 stations but 4 pages (~3.7 s). 3 h keeps the
#: bulk fetch to a single request while tolerating a late-publishing station.
DEFAULT_LOOKBACK_HOURS = 3
USER_AGENT = "france-river-flow-map/1.0 (open-source portfolio project)"


class HubeauError(RuntimeError):
    """Raised when Hub'Eau cannot be reached or returns an unusable payload."""


@dataclass
class FlowSnapshot:
    """Latest discharge reading for one station."""

    code_station: str
    flow_m3s: float | None = None
    flow_lps: float | None = None
    measured_at: pd.Timestamp | None = None

    @property
    def has_reading(self) -> bool:
        return self.flow_m3s is not None


@dataclass
class FlowResult:
    """Bulk fetch outcome, including partial-failure information."""

    snapshots: dict[str, FlowSnapshot] = field(default_factory=dict)
    ok: bool = True
    message: str = ""
    #: When this batch was retrieved (UTC). Surfaced in the UI as "last
    #: refreshed" so a cached page never looks more current than it is.
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def litres_per_second_to_m3s(value: float | int | None) -> float | None:
    """Convert a Hub'Eau discharge value (L/s) to m³/s.

    Returns ``None`` for missing values so absent readings are never rendered
    as a real measurement of zero.
    """
    if value is None:
        return None
    try:
        return float(value) / LITRES_PER_CUBIC_METRE
    except (TypeError, ValueError):
        return None


def _build_session() -> requests.Session:
    """Session with bounded retries and backoff for a throttling public API."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_SESSION = _build_session()


def _get_json(url: str, params: dict, timeout=DEFAULT_TIMEOUT) -> dict:
    """GET one page and return the decoded payload.

    Raises :class:`HubeauError` with a message that is safe to show a user --
    callers must never dump a raw response body into the UI.
    """
    try:
        response = _SESSION.get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("Hub'Eau request failed: %s", exc)
        raise HubeauError("Could not reach the Hub'Eau service.") from exc

    if response.status_code not in SUCCESS_STATUSES:
        logger.warning(
            "Hub'Eau returned HTTP %s for %s", response.status_code, response.url
        )
        raise HubeauError(
            f"Hub'Eau returned an unexpected response (HTTP {response.status_code})."
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise HubeauError("Hub'Eau returned a response that could not be read.") from exc

    if not isinstance(payload, dict):
        raise HubeauError("Hub'Eau returned an unexpected payload shape.")
    return payload


def _paginate(url: str, params: dict, max_pages: int = 10) -> list[dict]:
    """Follow Hub'Eau's ``next`` links up to ``max_pages`` and collect rows."""
    rows: list[dict] = []
    payload = _get_json(url, params)
    rows.extend(payload.get("data") or [])

    pages = 1
    next_url = payload.get("next")
    while next_url and pages < max_pages:
        payload = _get_json(next_url, params={})
        rows.extend(payload.get("data") or [])
        next_url = payload.get("next")
        pages += 1
    return rows


# --------------------------------------------------------------------------
# Stations
# --------------------------------------------------------------------------
STATION_FIELDS = (
    "code_station",
    "libelle_station",
    "libelle_cours_eau",
    "latitude_station",
    "longitude_station",
    "libelle_departement",
    "en_service",
)

STATION_COLUMNS = list(STATION_FIELDS)


def empty_stations() -> pd.DataFrame:
    """A correctly-shaped, empty station frame (used when the API is down)."""
    return pd.DataFrame(columns=STATION_COLUMNS)


def get_active_stations(department_code: str = "34") -> pd.DataFrame:
    """Return in-service hydrometric stations for one French department.

    The frame is deduplicated on ``code_station`` and guaranteed to contain
    :data:`STATION_COLUMNS`, with usable latitude/longitude on every row.
    """
    validate_department_code(department_code)
    params = {
        "code_departement": department_code,
        "en_service": 1,
        "format": "json",
        "size": 500,
        "fields": ",".join(STATION_FIELDS),
    }
    rows = _paginate(STATIONS_ENDPOINT, params)
    if not rows:
        return empty_stations()

    frame = pd.DataFrame(rows)
    for column in STATION_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    frame = frame[STATION_COLUMNS].copy()
    frame["latitude_station"] = pd.to_numeric(frame["latitude_station"], errors="coerce")
    frame["longitude_station"] = pd.to_numeric(frame["longitude_station"], errors="coerce")
    frame = frame.dropna(subset=["code_station", "latitude_station", "longitude_station"])
    frame = frame.drop_duplicates(subset="code_station").reset_index(drop=True)

    frame["libelle_station"] = frame["libelle_station"].fillna(frame["code_station"])
    frame["libelle_cours_eau"] = frame["libelle_cours_eau"].fillna("Unnamed watercourse")
    return frame


# --------------------------------------------------------------------------
# Observations
# --------------------------------------------------------------------------
OBSERVATION_FIELDS = ("code_station", "date_obs", "resultat_obs", "grandeur_hydro")


def _observations_frame(rows: list[dict], fallback_codes: list[str] | None = None) -> pd.DataFrame:
    """Normalise raw observation rows into a typed frame.

    ``code_station`` is present in current API responses, but when a single
    station was requested we fall back to the code we asked for rather than
    assuming a field that might disappear.
    """
    columns = ["code_station", "date_obs", "resultat_obs"]
    if not rows:
        return pd.DataFrame(columns=[*columns, "flow_m3s"])

    frame = pd.DataFrame(rows)
    for column in columns:
        if column not in frame.columns:
            frame[column] = None

    if fallback_codes and len(fallback_codes) == 1:
        frame["code_station"] = frame["code_station"].fillna(fallback_codes[0])

    frame = frame.dropna(subset=["code_station"])
    frame["date_obs"] = pd.to_datetime(frame["date_obs"], errors="coerce", utc=True)
    frame["resultat_obs"] = pd.to_numeric(frame["resultat_obs"], errors="coerce")
    frame["flow_m3s"] = frame["resultat_obs"] / LITRES_PER_CUBIC_METRE
    return frame.dropna(subset=["date_obs"]).sort_values("date_obs").reset_index(drop=True)


def _chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def get_latest_flows_for_stations(
    station_codes: list[str], lookback_hours: int = DEFAULT_LOOKBACK_HOURS
) -> FlowResult:
    """Fetch the latest discharge for many stations in as few requests as possible.

    ``code_entite`` accepts a comma-separated list, so one request covers up to
    :data:`MAX_CODES_PER_REQUEST` stations. A station with no reading inside the
    lookback window is returned with ``flow_m3s=None`` -- never a fabricated 0.

    A partial failure degrades gracefully: whatever was retrieved is returned
    with ``ok=False`` and a user-facing ``message``.
    """
    result = FlowResult(fetched_at=datetime.now(timezone.utc))
    codes = [code for code in dict.fromkeys(station_codes) if code]
    if not codes:
        return result

    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    failures = 0

    for batch in _chunk(codes, MAX_CODES_PER_REQUEST):
        params = {
            "code_entite": ",".join(batch),
            "grandeur_hydro": "Q",
            "date_debut_obs": since,
            "sort": "desc",
            "format": "json",
            "size": MAX_PAGE_SIZE,
            "fields": ",".join(OBSERVATION_FIELDS),
        }
        try:
            rows = _paginate(OBSERVATIONS_ENDPOINT, params, max_pages=5)
        except HubeauError as exc:
            logger.warning("Bulk flow fetch failed for %d stations: %s", len(batch), exc)
            failures += 1
            continue

        frame = _observations_frame(rows, fallback_codes=batch)
        if frame.empty:
            continue

        # sort_values in _observations_frame is ascending, so the last row per
        # station is the most recent one.
        latest = frame.groupby("code_station", as_index=False).last()
        for row in latest.itertuples(index=False):
            flow_lps = None if pd.isna(row.resultat_obs) else float(row.resultat_obs)
            result.snapshots[row.code_station] = FlowSnapshot(
                code_station=row.code_station,
                flow_m3s=litres_per_second_to_m3s(flow_lps),
                flow_lps=flow_lps,
                measured_at=row.date_obs,
            )

    result.fetched_at = datetime.now(timezone.utc)
    if failures:
        result.ok = False
        result.message = (
            "Live flow data is partially unavailable — Hub'Eau did not answer "
            "every request. Station locations are still shown."
        )
    return result


def get_latest_flow_for_station(
    code_station: str, lookback_hours: int = DEFAULT_LOOKBACK_HOURS
) -> FlowSnapshot:
    """Latest discharge for a single station (convenience wrapper)."""
    result = get_latest_flows_for_stations([code_station], lookback_hours=lookback_hours)
    return result.snapshots.get(code_station, FlowSnapshot(code_station=code_station))


def get_station_flow_history(code_station: str, hours: int = 24) -> pd.DataFrame:
    """Return the discharge time series for one station over the last ``hours``.

    Columns: ``code_station``, ``date_obs`` (UTC), ``resultat_obs`` (L/s),
    ``flow_m3s``. An empty frame means "no data published", not "zero flow".
    """
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    params = {
        "code_entite": code_station,
        "grandeur_hydro": "Q",
        "date_debut_obs": since,
        "sort": "asc",
        "format": "json",
        "size": MAX_PAGE_SIZE,
        "fields": ",".join(OBSERVATION_FIELDS),
    }
    rows = _paginate(OBSERVATIONS_ENDPOINT, params, max_pages=5)
    frame = _observations_frame(rows, fallback_codes=[code_station])
    if frame.empty:
        return frame
    frame = frame[frame["code_station"] == code_station]
    return frame.drop_duplicates(subset="date_obs").reset_index(drop=True)


# --------------------------------------------------------------------------
# Seasonal normals ("flow versus normal")
# --------------------------------------------------------------------------
#: How far back to look for monthly means. Hub'Eau typically publishes from
#: the 1990s onward; anything older adds rows without improving the median.
NORMALS_START_YEAR = 2000
#: Fewer than this many years for the calendar month and we decline to call it
#: a "normal" -- a two-year median is not a climatology.
MIN_YEARS_FOR_NORMAL = 5


@dataclass
class SeasonalNormal:
    """Typical discharge for one station in one calendar month."""

    code_station: str
    month: int
    normal_m3s: float | None = None
    years: int = 0

    def ratio(self, current_m3s: float | None) -> float | None:
        """Current discharge as a multiple of normal. None when undefined."""
        if current_m3s is None or self.normal_m3s in (None, 0):
            return None
        return float(current_m3s) / float(self.normal_m3s)


def get_seasonal_normals(
    station_codes: list[str], month: int | None = None
) -> dict[str, SeasonalNormal]:
    """Median monthly-mean discharge for ``month``, per station.

    Uses Hub'Eau's *elaborated* monthly means (``QmM``), which are validated
    aggregates rather than provisional real-time values. One request covers up
    to :data:`MAX_CODES_PER_REQUEST` stations, so a whole department costs a
    couple of calls.

    The median (not the mean) is used because river regimes are strongly
    right-skewed: a single flood year would drag a mean far above what a
    typical August actually looks like.

    Stations with fewer than :data:`MIN_YEARS_FOR_NORMAL` years of data for the
    month are returned with ``normal_m3s=None`` rather than a weak estimate.
    """
    target_month = month or datetime.now(timezone.utc).month
    codes = [code for code in dict.fromkeys(station_codes) if code]
    normals: dict[str, SeasonalNormal] = {}
    if not codes:
        return normals

    for batch in _chunk(codes, MAX_CODES_PER_REQUEST):
        params = {
            "code_entite": ",".join(batch),
            "grandeur_hydro_elab": GRANDEUR_MONTHLY_MEAN,
            "date_debut_obs_elab": f"{NORMALS_START_YEAR}-01-01",
            "format": "json",
            "size": MAX_PAGE_SIZE,
            "fields": "code_station,date_obs_elab,resultat_obs_elab",
        }
        try:
            rows = _paginate(OBS_ELAB_ENDPOINT, params, max_pages=20)
        except HubeauError as exc:
            logger.warning("Seasonal normals unavailable for %d stations: %s", len(batch), exc)
            continue
        if not rows:
            continue

        frame = pd.DataFrame(rows)
        for column in ("code_station", "date_obs_elab", "resultat_obs_elab"):
            if column not in frame.columns:
                frame[column] = None
        frame["date_obs_elab"] = pd.to_datetime(frame["date_obs_elab"], errors="coerce")
        frame["resultat_obs_elab"] = pd.to_numeric(frame["resultat_obs_elab"], errors="coerce")
        frame = frame.dropna(subset=["code_station", "date_obs_elab", "resultat_obs_elab"])
        if frame.empty:
            continue

        same_month = frame[frame["date_obs_elab"].dt.month == target_month]
        for code, group in same_month.groupby("code_station"):
            years = int(group["date_obs_elab"].dt.year.nunique())
            if years < MIN_YEARS_FOR_NORMAL:
                normals[str(code)] = SeasonalNormal(str(code), target_month, None, years)
                continue
            median_lps = float(group["resultat_obs_elab"].median())
            normals[str(code)] = SeasonalNormal(
                str(code), target_month, litres_per_second_to_m3s(median_lps), years
            )

    return normals
