#!/usr/bin/env python
"""Build the commune registry that backs the national city filter.

Writes:

  data/processed/communes.json   -- registry consumed by src/config.py

The national view needs to offer every gauged commune in France *before* a
department has been chosen, and it cannot pay for that at page load: the
Hub'Eau stations endpoint caps ``code_departement`` at 50 values, so the whole
country is 9 requests, and the service's latency for them is both high and
wildly variable -- 3 s, 23 s and 42 s measured minutes apart. That is fine for
a build step and unacceptable on a landing page, so the list is preprocessed
here and committed, exactly as the river, boundary and dam layers are.

Only the commune name and its department codes are kept. Station details are
still fetched live per department when a city is actually chosen, so nothing
here can go stale in a way that shows a wrong reading -- at worst a newly
gauged commune is missing from the dropdown until this is re-run.

    python scripts/prepare_communes.py
    python scripts/prepare_communes.py --force
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import COMMUNES_PATH, PROCESSED_DIR, load_regions
from src.services.hubeau import get_active_stations_for_departments


def fetch_communes() -> dict[str, set[str]]:
    """Map every gauged commune name to the departments it appears in.

    Deliberately the same call the app makes for a department, so a commune
    reaches the registry only if the app could actually show a station in it:
    stations without usable coordinates are dropped by both, and a registry
    built any other way would offer cities that turn out to have nothing.
    """
    codes = [region.code for region in load_regions().values() if not region.is_national]
    print(f"  {len(codes)} departments, chunked ...", flush=True)
    stations = get_active_stations_for_departments(codes)

    communes: dict[str, set[str]] = {}
    for name, department in zip(stations["libelle_commune"], stations["code_departement"]):
        name = str(name or "").strip()
        department = str(department or "").strip()
        if name and department:
            communes.setdefault(name, set()).add(department)
    return communes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="rebuild even if the registry exists"
    )
    args = parser.parse_args()

    if COMMUNES_PATH.exists() and not args.force:
        print(f"{COMMUNES_PATH} already exists -- use --force to rebuild.")
        return 0

    print("Fetching gauged communes from Hub'Eau (this is slow by design):")
    started = time.time()
    communes = fetch_communes()
    if not communes:
        print("No communes returned -- refusing to write an empty registry.")
        return 1

    payload = {
        "generated_at": time.strftime("%Y-%m-%d"),
        "communes": [
            {"name": name, "departments": sorted(departments)}
            for name, departments in sorted(communes.items())
        ],
    }
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    COMMUNES_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    shared = sum(1 for c in payload["communes"] if len(c["departments"]) > 1)
    print(
        f"Wrote {len(payload['communes']):,} communes to {COMMUNES_PATH} "
        f"({shared} span more than one department) in {time.time() - started:.0f}s."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
