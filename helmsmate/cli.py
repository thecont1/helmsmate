"""Command line — one entry point for the engine, the API and the MCP server.

    helmsmate build deck.yaml --out dist/index.html
    helmsmate validate deck.yaml
    helmsmate serve --port 8787
    helmsmate mcp                    # stdio MCP server, for an LLM client
    helmsmate schema                 # the deck contract, as JSON
    helmsmate layouts                # the layout catalog
    helmsmate themes                 # available themes
    helmsmate decks                  # decks in the workspace
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import paths, spec, themes
from .engine import BuildError, build_html
from .store import DeckStore
from .validate import ERROR, validate_deck


def _load_deck(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def cmd_build(args: argparse.Namespace) -> int:
    deck_path = Path(args.deck)
    if not deck_path.is_absolute():
        deck_path = paths.repo_root() / deck_path
    if not deck_path.exists():
        print(f"No such deck: {deck_path}", file=sys.stderr)
        return 1

    deck = _load_deck(deck_path)
    issues = validate_deck(deck)
    errors = [i for i in issues if i.severity == ERROR]
    if errors and not args.force:
        print(f"{deck_path.name}: {len(errors)} validation error(s)")
        for issue in issues:
            print(f"  {issue}")
        return 1

    # Output lands relative to the working directory, not to wherever the
    # package happens to be installed.
    out = Path(args.out) if args.out else Path("dist") / "index.html"
    try:
        result = build_html(deck)
    except BuildError as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.html, encoding="utf-8")
    print(f"Built {out} ({result.size:,} bytes, {result.slides} slides)")
    for warning in result.warnings:
        print(f"  warning: {warning}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    deck_path = Path(args.deck)
    if not deck_path.is_absolute():
        deck_path = paths.repo_root() / deck_path
    deck = _load_deck(deck_path)
    issues = validate_deck(deck)
    if not issues:
        print(f"{deck_path.name}: valid.")
        return 0
    for issue in issues:
        print(f"  {issue}")
    return 1 if any(i.severity == ERROR for i in issues) else 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .api import serve

    serve(
        host=args.host,
        port=args.port,
        workspace=Path(args.workspace) if args.workspace else None,
        token=args.token,
    )
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp import stdio_main

    argv = []
    if args.workspace:
        argv += ["--workspace", args.workspace]
    return stdio_main(argv)


def cmd_schema(args: argparse.Namespace) -> int:
    if args.layout:
        if args.layout not in spec.LAYOUTS:
            print(f"Unknown layout: {args.layout}", file=sys.stderr)
            return 1
        print(json.dumps(spec.layout_schema(args.layout), indent=2))
        return 0
    print(spec.schema_json())
    return 0


def cmd_layouts(args: argparse.Namespace) -> int:
    for entry in spec.layout_catalog():
        print(f"{entry['layout']:<9} {entry['summary']}")
        print(f"          requires: {', '.join(entry['required_fields']) or 'nothing'}")
    return 0


def cmd_themes(args: argparse.Namespace) -> int:
    for theme in themes.list_themes():
        modes = ", ".join(theme["modes"])
        print(f"{theme['name']:<18} {theme['label']}  [{modes}]")
    return 0


def cmd_decks(args: argparse.Namespace) -> int:
    store = DeckStore(Path(args.workspace) if args.workspace else None)
    records = store.list()
    if not records:
        print(f"No decks in {store.workspace}")
        return 0
    for record in records:
        print(f"{record.id:<34} {record.slides:>3} slides  {record.bytes:>9,} bytes  {record.updated_at}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="helmsmate", description="HelmsMate deck engine")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="compile a deck YAML into HTML")
    p.add_argument("deck", nargs="?", default="deck.example.yaml")
    p.add_argument("--out", "-o", default=None, help="output HTML path")
    p.add_argument("--force", action="store_true", help="build despite validation errors")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("validate", help="check a deck without building it")
    p.add_argument("deck", nargs="?", default="deck.example.yaml")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("serve", help="run the REST API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--workspace", default=None)
    p.add_argument("--token", default=None, help="require this bearer token")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("mcp", help="run the MCP server over stdio")
    p.add_argument("--workspace", default=None)
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("schema", help="print the deck contract as JSON")
    p.add_argument("--layout", default=None, help="one layout's schema")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("layouts", help="list the slide layouts")
    p.set_defaults(func=cmd_layouts)

    p = sub.add_parser("themes", help="list available themes")
    p.set_defaults(func=cmd_themes)

    p = sub.add_parser("decks", help="list decks in the workspace")
    p.add_argument("--workspace", default=None)
    p.set_defaults(func=cmd_decks)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
