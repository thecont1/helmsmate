#!/usr/bin/env python3
"""HelmsMate build step.

Reads deck.yaml, a named theme, and the generic HTML template, then writes a
single self-contained index.html with zero runtime dependencies.

Usage:
    python engine/build.py
    python engine/build.py path/to/deck.yaml
    python engine/build.py path/to/deck.yaml --out out.html

The rendering lives in the `helmsmate` package; this script is kept so the
original entry point keeps working.

Authoring conventions:
    title : newlines fold — the browser wraps titles (text-wrap:balance)
    note / stat.small : literal newlines render as <br>
    lede / lede2 / lede_after / card.p : newlines fold into natural prose
    **text** renders <b>text</b> in any text field
    figure : raw HTML (SVG), passed through untouched
    figure_asset : path to an image in the workspace, inlined at build time
    grid_mt : optional integer px margin-top override for the card/figure grid
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from helmsmate import paths  # noqa: E402
from helmsmate.engine import BuildError, build_html  # noqa: E402
from helmsmate.validate import ERROR, validate_deck  # noqa: E402

import yaml  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="HelmsMate deck builder")
    parser.add_argument(
        "deck",
        nargs="?",
        default=str(REPO / "deck.example.yaml"),
        help="Path to deck YAML",
    )
    parser.add_argument(
        "--out",
        "-o",
        default=None,
        help="Output HTML path (default: <repo>/dist/index.html)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Build despite validation errors"
    )
    args = parser.parse_args()

    deck_path = Path(args.deck)
    if not deck_path.is_absolute():
        deck_path = REPO / deck_path

    with open(deck_path, "r", encoding="utf-8") as f:
        deck = yaml.safe_load(f) or {}

    issues = validate_deck(deck)
    errors = [i for i in issues if i.severity == ERROR]
    if errors and not args.force:
        print(f"{deck_path.name}: {len(errors)} validation error(s)", file=sys.stderr)
        for issue in issues:
            print(f"  {issue}", file=sys.stderr)
        raise SystemExit(1)

    try:
        result = build_html(deck)
    except BuildError as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

    target = Path(args.out) if args.out else paths.repo_root() / "dist" / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(result.html)

    print(f"Built {target} ({result.size:,} bytes) from {deck_path.name}")
    for warning in result.warnings:
        print(f"  warning: {warning}")


if __name__ == "__main__":
    main()
