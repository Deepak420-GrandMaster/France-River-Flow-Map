#!/usr/bin/env python
"""Manual connectivity probe for the Hub'Eau Hydrométrie API.

Replaces the original root-level ``test_api.py`` (station reference lookup) and
``test_flow.py`` (real-time discharge lookup). Both checks are preserved here;
this is a **diagnostic CLI**, not part of the Streamlit app, and it is the
quickest way to tell "the app is broken" apart from "Hub'Eau is down".

    python scripts/check_hubeau_api.py                     # both checks
    python scripts/check_hubeau_api.py --department 34
    python scripts/check_hubeau_api.py --station Y210001001

Notes worth remembering (verified against the live API):
  * observations are filtered with ``code_entite``, not ``code_station``
  * HTTP 206 is a success (partial content)
  * discharge is published in L/s and converted to m³/s here
  * the API throttles bursts -- retries and backoff are built into the client
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.hubeau import (
    HubeauError,
    get_active_stations,
    get_latest_flows_for_stations,
    get_station_flow_history,
)


def check_stations(department: str) -> list[str]:
    print(f"\n=== Station reference — department {department} ===")
    try:
        stations = get_active_stations(department)
    except HubeauError as exc:
        print(f"FAILED: {exc}")
        return []

    print(f"Active stations: {len(stations)}")
    for row in stations.head(5).itertuples(index=False):
        print(
            f"  {row.code_station}  {row.libelle_station[:38]:<38} "
            f"{str(row.libelle_cours_eau)[:22]:<22} "
            f"({row.latitude_station:.4f}, {row.longitude_station:.4f})"
        )
    if len(stations) > 5:
        print(f"  … and {len(stations) - 5} more")
    return stations["code_station"].tolist()


def check_flows(codes: list[str]) -> None:
    print(f"\n=== Latest discharge — bulk fetch for {len(codes)} station(s) ===")
    if not codes:
        print("Skipped: no station codes available.")
        return

    result = get_latest_flows_for_stations(codes)
    print(f"ok={result.ok}  readings={len(result.snapshots)}/{len(codes)}")
    if result.message:
        print(f"message: {result.message}")
    for snapshot in list(result.snapshots.values())[:5]:
        print(
            f"  {snapshot.code_station}  {snapshot.flow_lps:>12,.0f} L/s  "
            f"= {snapshot.flow_m3s:>9.3f} m³/s  @ {snapshot.measured_at}"
        )


def check_history(code: str) -> None:
    print(f"\n=== 24 h discharge history — {code} ===")
    try:
        history = get_station_flow_history(code, hours=24)
    except HubeauError as exc:
        print(f"FAILED: {exc}")
        return
    if history.empty:
        print("No observations published in this window.")
        return
    print(f"rows={len(history)}  from {history['date_obs'].min()} to {history['date_obs'].max()}")
    print(f"min={history['flow_m3s'].min():.3f}  max={history['flow_m3s'].max():.3f} m³/s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--department", default="34", help="INSEE department code (default: 34)")
    parser.add_argument("--station", default=None, help="Station code for the history check")
    args = parser.parse_args()

    codes = check_stations(args.department)
    check_flows(codes[:10])
    target = args.station or (codes[0] if codes else None)
    if target:
        check_history(target)
    print("\nDone.")
    return 0 if codes else 1


if __name__ == "__main__":
    raise SystemExit(main())
