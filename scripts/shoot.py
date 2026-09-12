#!/usr/bin/env python3
"""HelmChart screenshot harness.

Captures each slide of the built index.html to the shots/ directory.

Usage:
    python scripts/shoot.py
    python scripts/shoot.py --width 1440 --height 900
"""

import argparse
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:
    print("This harness requires Playwright: uv add playwright", file=sys.stderr)
    raise

REPO = Path(__file__).resolve().parent.parent
DEFAULT_HTML = REPO / "dist" / "index.html"
SHOTS_DIR = REPO / "shots"


def main():
    parser = argparse.ArgumentParser(description="HelmChart screenshot harness")
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--out", type=Path, default=SHOTS_DIR)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        page.goto(args.html.resolve().as_uri())
        page.wait_for_timeout(500)

        total = page.evaluate("() => document.querySelectorAll('.slide').length")
        for i in range(1, total + 1):
            page.goto(args.html.resolve().as_uri() + f"#/{i}")
            page.wait_for_timeout(700)
            path = args.out / f"slide-{i:02d}-{args.width}x{args.height}.png"
            page.screenshot(path=path, full_page=False)
            print(path)

        browser.close()


if __name__ == "__main__":
    main()
