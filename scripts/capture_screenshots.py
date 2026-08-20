#!/usr/bin/env python
"""Capture the README screenshots from a running instance of the app.

Optional developer tool. Playwright is deliberately *not* a project
dependency -- it is only needed to refresh the images in `assets/`:

    python -m pip install playwright && python -m playwright install chromium
    python -m streamlit run app.py          # in another terminal
    python scripts/capture_screenshots.py

Each shot drives the real UI, so the images can never drift from what the app
actually renders.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import PROJECT_ROOT

ASSETS = PROJECT_ROOT / "assets"
VIEWPORT = {"width": 1600, "height": 1000}
#: Streamlit streams its layout in; the map iframe needs a moment more.
SETTLE_SECONDS = 6
#: 1x keeps each PNG around 500 KB. A 2x capture looks marginally sharper but
#: triples the repository weight for no real gain in a README.
DEVICE_SCALE = 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8501")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Playwright is not installed. Run:\n"
            "  python -m pip install playwright\n"
            "  python -m playwright install chromium"
        ) from None

    ASSETS.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=DEVICE_SCALE)

        def settle(seconds: float = SETTLE_SECONDS) -> None:
            page.wait_for_timeout(int(seconds * 1000))

        def shot(name: str) -> None:
            path = ASSETS / f"{name}.png"
            page.screenshot(path=str(path))
            size_kb = path.stat().st_size / 1024
            print(f"  wrote {path.relative_to(PROJECT_ROOT)} ({size_kb:.0f} KB)")

        print(f"Opening {args.url}")
        page.goto(args.url, wait_until="networkidle")
        settle(8)
        shot("screenshot-national")

        # Switch to the Hérault department for the live-station view.
        print("Selecting Hérault…")
        page.locator('[data-testid="stSidebar"]').get_by_role("combobox").first.click()
        page.keyboard.type("Hérault")
        settle(1)
        page.keyboard.press("Enter")
        settle(10)
        shot("screenshot-department")

        # Turn on the seasonal comparison.
        print("Enabling flow vs normal…")
        # Scope to the sidebar: the phrase also appears in the About text.
        page.locator('[data-testid="stSidebar"]').get_by_text(
            "Flow vs normal", exact=True
        ).first.click()
        settle(10)
        shot("screenshot-flow-vs-normal")

        browser.close()

    print("\nDone. Reference them from README.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
