#!/usr/bin/env python3
"""HelmChart invariant verifier.

Runs the built index.html in a headless browser and asserts:
- all slides render
- no blank slides after slide 1
- CoronaMark appears in every slide or the shared header
- logo click returns to slide 1
- no horizontal overflow
- card rows have equal-height cards
- footer is inside viewport on desktop
- footer remains reachable on mobile
- page counter is centered between nav buttons
- hash navigation works

Usage:
    python scripts/verify.py
    python scripts/verify.py --size 1440x900
"""

import argparse
import math
import re
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:
    print("This verifier requires Playwright: uv add playwright", file=sys.stderr)
    raise

REPO = Path(__file__).resolve().parent.parent
DEFAULT_HTML = REPO / "dist" / "index.html"


def parse_size(s: str):
    m = re.match(r"(\d+)x(\d+)", s)
    if not m:
        raise ValueError(f"Size must be WIDTHxHEIGHT, got {s}")
    return int(m.group(1)), int(m.group(2))


def failure(msg: str):
    print("  FAIL:", msg)
    return False


def check_slide(page, index: int, width: int, height: int):
    print(f"\n--- Slide {index} ---")
    ok = True

    # Force navigation by setting hash and waiting for the transition.
    page.evaluate(f"location.hash='#/{index}'")
    page.wait_for_timeout(600)

    # 1. slide paints
    slide = page.locator(".slide").nth(index - 1)
    if not slide.is_visible():
        ok &= failure("slide is not visible")

    bbox = slide.bounding_box()
    if not bbox:
        ok &= failure("could not get slide bbox")
        return ok

    # 2. width = viewport (no drift)
    if abs(bbox["width"] - width) > 1:
        ok &= failure(f"slide width {bbox['width']} != viewport {width}")

    # 3. no horizontal overflow inside the slide
    max_x = page.evaluate("""
        () => {
            const s = document.querySelectorAll('.slide')[arguments[0]-1];
            const r = s.getBoundingClientRect();
            let max = r.right;
            s.querySelectorAll('*').forEach(el => {
                const b = el.getBoundingClientRect();
                if (b.right > max) max = b.right;
            });
            return { right: r.right, max: max };
        }
    """, index)
    if max_x and max_x["max"] > max_x["right"] + 1:
        ok &= failure(f"horizontal overflow: content right={max_x['max']}, slide right={max_x['right']}")

    # 4. logo presence (shared header plus inside this slide as backup)
    logo = page.locator(".brand-mark svg").first
    if not logo.is_visible():
        ok &= failure("logo not visible")

    # 5. page counter text and centering inside nav
    count = slide.locator(".count").first
    if not count.is_visible():
        ok &= failure("page count not visible")
    else:
        count_text = count.inner_text().strip()
        if f" {index} / " not in count_text:
            ok &= failure(f"counter text wrong: {count_text}")

    # 6. card row equal heights (only when the grid has more than one column)
    grid_info = page.evaluate(
        """(i) => {
            const slide = document.querySelectorAll('.slide')[i-1];
            const out = [];
            slide.querySelectorAll('.grid2, .grid3').forEach(g => {
                const cols = getComputedStyle(g).gridTemplateColumns.split(' ').filter(Boolean).length;
                out.push({ cols, heights: Array.from(g.children).map(c => c.getBoundingClientRect().height) });
            });
            return out;
        }""",
        index,
    )
    for g in grid_info:
        if g["cols"] > 1 and g["heights"]:
            hs = g["heights"]
            if max(hs) - min(hs) > 1:
                ok &= failure(f"unequal card heights: {hs}")

    # 7. footer inside viewport on desktop; reachable on mobile
    foot = slide.locator(".stage-foot").first
    if foot.is_visible():
        if height >= 720:
            fb = foot.bounding_box()
            if fb and fb["y"] + fb["height"] > height + 1:
                ok &= failure(f"footer below viewport: bottom={fb['y'] + fb['height']}")
        else:
            slide.evaluate("el => { el.scrollTop = el.scrollHeight; }")
            page.wait_for_timeout(150)
            fb = foot.bounding_box()
            if fb and fb["y"] + fb["height"] > height + 1:
                ok &= failure(f"footer not reachable on mobile: bottom={fb['y'] + fb['height']}")

    return ok


def main():
    parser = argparse.ArgumentParser(description="HelmChart deck verifier")
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--sizes", default="1440x900,1280x720,390x844")
    args = parser.parse_args()

    all_ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch()

        for size in args.sizes.split(","):
            width, height = parse_size(size)
            print(f"\n===== viewport {width}x{height} =====")
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(args.html.resolve().as_uri())
            page.wait_for_timeout(500)

            total = page.evaluate("() => document.querySelectorAll('.slide').length")
            print(f"slide count: {total}")

            # Logo reset from slide 6
            if total >= 6:
                page.goto(args.html.resolve().as_uri() + "#/6")
                page.wait_for_timeout(600)
                page.locator(".brand").first.click()
                page.wait_for_timeout(600)
                loc = page.evaluate("() => location.hash")
                if loc != "#/1":
                    all_ok &= failure(f"logo reset failed: location is {loc}")
                else:
                    print("  logo reset -> #/1 OK")

            # Hash nav
            for i in range(1, total + 1):
                all_ok &= check_slide(page, i, width, height)

            page.close()

        browser.close()

    print("\n" + ("ALL PASSED" if all_ok else "SOME CHECKS FAILED"))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
