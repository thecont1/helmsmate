"""HelmsMate — YAML decks compiled to self-contained HTML presentations.

Public surface:

    from helmsmate import build_html, validate_deck, list_themes

    build_html(deck)        -> BuildResult (html, slides, warnings, outline)
    validate_deck(deck)     -> list of problems (path, message, hint)
    list_themes()           -> catalog of available themes

The API and MCP layers build on the same functions, so anything an LLM can
reach through a tool is reachable through the library too.
"""

from __future__ import annotations

from .engine import BuildError, BuildResult, build_html
from .spec import (
    LAYOUTS,
    deck_json_schema,
    layout_catalog,
    layout_names,
    layout_schema,
    schema_document,
)
from .themes import list_theme_names, list_themes, load_theme
from .validate import ValidationIssue, validate_deck

__version__ = "0.1.0"

__all__ = [
    "BuildError",
    "BuildResult",
    "LAYOUTS",
    "ValidationIssue",
    "build_html",
    "deck_json_schema",
    "layout_catalog",
    "layout_names",
    "layout_schema",
    "list_theme_names",
    "list_themes",
    "load_theme",
    "schema_document",
    "validate_deck",
]
