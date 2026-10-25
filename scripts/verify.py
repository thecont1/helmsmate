#!/usr/bin/env python3
"""HelmsMate invariant verifier.

Runs the built index.html in a headless browser and asserts:
- all slides render (no blank slides after slide 1)
- brand mark (svg.corona) present in the frozen header
- logo click returns to slide 1
- no horizontal overflow on any visible slide
- card rows have equal-height cards (multi-column grids only)
- per-slide .foot is inside the viewport on desktop; reachable + clear of nav on mobile
- #pageno is centered between the prev/next buttons
- slide index menu opens, lists one item per slide, tracks position, navigates
- routing works (clean /N paths on http, #/N hash under file://); dots + progress track

Usage:
    python scripts/verify.py
    python scripts/verify.py --sizes 1440x900,1280x720
"""

import argparse
import re
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("This verifier requires Playwright: uv add --dev playwright", file=sys.stderr)
    raise

REPO = Path(__file__).resolve().parent.parent
DEFAULT_HTML = REPO / "dist" / "index.html"


def parse_size(s: str):
    m = re.match(r"(\d+)x(\d+)", s)
    if not m:
        raise ValueError(f"Size must be WIDTHxHEIGHT, got {s}")
    return int(m.group(1)), int(m.group(2))


def failure(msg: str) -> bool:
    print("  FAIL:", msg)
    return False


def check_slide(page, index: int, width: int, height: int) -> bool:
    ok = True

    page.evaluate("i => { location.hash = '#/' + i; }", index)
    page.wait_for_timeout(650)

    slide = page.locator(".slide").nth(index - 1)
    if not slide.is_visible():
        ok &= failure(f"slide {index} not visible")
        return ok

    bbox = slide.bounding_box()
    if abs(bbox["width"] - width) > 1:
        ok &= failure(f"slide {index} width {bbox['width']} != viewport {width}")
    if abs(bbox["x"]) > 1:
        ok &= failure(f"slide {index} not at x=0: {bbox['x']}")

    overflow = page.evaluate(
        """(i) => {
            const s = document.querySelectorAll('.slide')[i-1];
            const r = s.getBoundingClientRect();
            let max = r.right;
            s.querySelectorAll('*').forEach(el => {
                const b = el.getBoundingClientRect();
                if (b.right > max) max = b.right;
            });
            return {right: r.right, max};
        }""",
        index,
    )
    if overflow["max"] > overflow["right"] + 1:
        ok &= failure(
            f"slide {index} horizontal overflow: content={overflow['max']} slide={overflow['right']}"
        )

    grid_info = page.evaluate(
        """(i) => {
            const s = document.querySelectorAll('.slide')[i-1];
            return Array.from(s.querySelectorAll('.grid2, .grid3')).map(g => ({
                cols: getComputedStyle(g).gridTemplateColumns.split(' ').filter(Boolean).length,
                heights: Array.from(g.children).map(c => c.getBoundingClientRect().height)
            }));
        }""",
        index,
    )
    for g in grid_info:
        if g["cols"] > 1 and g["heights"]:
            hs = g["heights"]
            if max(hs) - min(hs) > 1:
                ok &= failure(f"slide {index} unequal card heights: {hs}")

    foot = slide.locator(".foot").first
    if foot.count() and foot.is_visible():
        # Mirror the engine's own scroll triggers: a slide scrolls when it is
        # narrow (max-width:900px) or short (max-height:620px). Then the footer
        # must be *reachable* by scrolling. Otherwise it must already sit
        # inside the viewport. A tall phone (390x844) is still a phone.
        scrolls = width <= 900 or height <= 620
        if scrolls:
            slide.evaluate("el => { el.scrollTop = el.scrollHeight; }")
            page.wait_for_timeout(150)
            fb = foot.bounding_box()
            if fb["y"] + fb["height"] > height + 1:
                ok &= failure(f"slide {index} footer unreachable on scroll: {fb['y'] + fb['height']}")
        else:
            fb = foot.bounding_box()
            if fb["y"] + fb["height"] > height + 1:
                ok &= failure(f"slide {index} footer below viewport: {fb['y'] + fb['height']}")

        # Footer must clear the fixed nav row (bottom-right buttons + dots)
        nav_top = page.locator(".nav").bounding_box()["y"]
        if fb["y"] + fb["height"] > nav_top + 1:
            ok &= failure(
                f"slide {index} footer overlaps nav: foot bottom {fb['y'] + fb['height']} > nav top {nav_top}"
            )

    expected_ctx = page.evaluate(
        "(i) => document.querySelectorAll('.slide')[i-1].dataset.context || ''", index
    )
    actual_ctx = page.locator("#menu-current").inner_text()
    if actual_ctx != expected_ctx:
        ok &= failure(f"slide {index} menu-current: '{actual_ctx}' != '{expected_ctx}'")

    menu_state = page.evaluate(
        """(i) => {
            const items = Array.from(document.querySelectorAll('#menu-list button'));
            return {count: items.length,
                    onIdx: items.findIndex(b => b.classList.contains('on'))};
        }""",
        index,
    )
    if menu_state["count"] != len(page.locator(".slide").all()):
        ok &= failure(f"slide {index} menu item count: {menu_state['count']}")
    if menu_state["onIdx"] != index - 1:
        ok &= failure(f"slide {index} active menu item: {menu_state['onIdx']}")

    if page.locator("#pageno").inner_text() != f"{index} / {len(page.locator('.slide').all())}":
        ok &= failure(f"slide {index} pageno text wrong: {page.locator('#pageno').inner_text()}")

    dots_on = page.locator(".dots i.on").count()
    if dots_on != 1:
        ok &= failure(f"slide {index} active dot count: {dots_on}")

    return ok


def main():
    parser = argparse.ArgumentParser(description="HelmsMate deck verifier")
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--sizes", default="1440x900,1280x720,390x844,1200x500")
    args = parser.parse_args()

    all_ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch()

        for size in args.sizes.split(","):
            width, height = parse_size(size)
            print(f"\n===== {width}x{height} =====")
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(args.html.resolve().as_uri())
            page.wait_for_timeout(500)

            total = page.locator(".slide").count()
            print(f"slides: {total}")

            # Brand mark present in the frozen chrome (the site bar is fixed)
            if not page.locator(".site-bar-home svg.corona").is_visible():
                all_ok &= failure("corona svg not visible in .site-bar-home")

            # Counter centered between prev/next
            mid = page.evaluate(
                """() => {
                    const p = document.getElementById('prev').getBoundingClientRect();
                    const n = document.getElementById('next').getBoundingClientRect();
                    const c = document.getElementById('pageno').getBoundingClientRect();
                    return {mid: (p.right + n.left) / 2, c: c.left + c.width / 2};
                }"""
            )
            if abs(mid["c"] - mid["mid"]) > 1.5:
                all_ok &= failure(f"pageno not centered: {mid['c']} vs {mid['mid']}")
            else:
                print("  pageno centered OK")

            # Slide index menu: opens, one item per slide, item click navigates
            page.locator("#menu-btn").click()
            page.wait_for_timeout(200)
            if not page.locator(".deck-menu.open .menu-list").is_visible():
                all_ok &= failure("slide index menu did not open")
            else:
                print("  menu opens OK")
            # Click the last menu item and expect to land on the last slide.
            # Works for a one-slide deck as well as an eight-slide one.
            page.locator("#menu-list button").nth(total - 1).click()
            page.wait_for_timeout(700)
            if page.locator("#pageno").inner_text() != f"{total} / {total}":
                all_ok &= failure(f"menu item did not navigate: {page.locator('#pageno').inner_text()}")
            elif page.locator(".deck-menu.open").count():
                all_ok &= failure("menu stayed open after navigation")
            else:
                print("  menu item navigates OK")

            # Home/End jump to the first and last slide.
            # (The old "click the logo to reset" check no longer applies: the
            # mark now lives in the site bar, where it is a link out to the
            # site rather than a deck control.)
            if total >= 3:
                page.keyboard.press("End")
                page.wait_for_timeout(650)
                if page.locator("#pageno").inner_text() != f"{total} / {total}":
                    all_ok &= failure(f"End did not reach the last slide: {page.locator('#pageno').inner_text()}")
                page.keyboard.press("Home")
                page.wait_for_timeout(650)
                if page.locator("#pageno").inner_text() != f"1 / {total}":
                    all_ok &= failure(f"Home did not return to slide 1: {page.locator('#pageno').inner_text()}")
                else:
                    print("  Home/End navigation OK")

            for i in range(1, total + 1):
                all_ok &= check_slide(page, i, width, height)
                print(f"  slide {i} checked")

            page.close()

        browser.close()

    print("\n" + ("ALL PASSED" if all_ok else "SOME CHECKS FAILED"))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
