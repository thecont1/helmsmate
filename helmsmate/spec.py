"""Deck schema — the single source of truth for what a HelmsMate deck is.

This module is the only place that knows the deck format. The renderer
(``engine.py``) draws HTML from it, the validator (``validate.py``) checks
decks against it, and the API/MCP layers (``api.py``, ``mcp.py``) publish it
as JSON Schema so an LLM can discover the contract without reading prose.

Keep it declarative. If a layout gains a field, add it here first — the
catalog, the JSON Schema and the error messages all derive from these tables.

Text kinds and their rendering rules (mirrored by the renderer):

``text``      one line; newlines fold into spaces. Inline ``**bold**``,
              ``*italic*`` and ``` `code` ``` are honoured.
``lines``     newlines are preserved and become ``<br>``.
``richtext``  newlines fold into natural prose; inline markup honoured.
``html``      passed through untouched. Use only for trusted SVG/HTML.
``asset``     a path to an SVG/raster in the workspace; inlined at build time
              so the finished deck stays self-contained.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "1.0"

# ── Field kinds ────────────────────────────────────────────────────────────

TEXT = "text"
LINES = "lines"
RICHTEXT = "richtext"
HTML = "html"
ASSET = "asset"
INT = "int"
BOOL = "bool"
CARDS = "cards"
STATS = "stats"


@dataclass(frozen=True)
class Field:
    """One authored field on a slide."""

    name: str
    kind: str
    description: str
    required: bool = False
    max_items: int | None = None
    item_fields: tuple[str, ...] = ()
    example: str = ""

    def to_schema(self) -> dict[str, Any]:
        """JSON Schema fragment for this field."""
        base: dict[str, Any] = {"description": self.description}
        if self.kind == TEXT:
            base["type"] = "string"
        elif self.kind in (LINES, RICHTEXT):
            base["type"] = "string"
        elif self.kind == HTML:
            base["type"] = "string"
            base["description"] += " Raw HTML — trusted content only."
        elif self.kind == ASSET:
            base["type"] = "string"
            base["description"] += (
                " Path to an asset (svg/png/jpg) relative to the deck workspace; "
                "it is inlined at build time."
            )
        elif self.kind == INT:
            base["type"] = "integer"
        elif self.kind == BOOL:
            base["type"] = "boolean"
        elif self.kind == CARDS:
            base["type"] = "array"
            base["maxItems"] = self.max_items if self.max_items is not None else 8
            base["items"] = {
                "type": "object",
                "properties": {
                    "k": {"type": "string", "description": "Card eyebrow / kicker"},
                    "h": {"type": "string", "description": "Card heading"},
                    "p": {"type": "string", "description": "Card body prose"},
                },
                "required": ["h"],
            }
        elif self.kind == STATS:
            base["type"] = "array"
            base["maxItems"] = self.max_items if self.max_items is not None else 6
            base["items"] = {
                "type": "object",
                "properties": {
                    "big": {"type": "string", "description": "Large figure or short label"},
                    "small": {"type": "string", "description": "Caption under the figure"},
                },
                "required": ["big"],
            }
        if self.example:
            base["examples"] = [self.example]
        return base


@dataclass(frozen=True)
class Layout:
    """One slide layout and the fields it consumes."""

    name: str
    summary: str
    fields: tuple[Field, ...] = field(default_factory=tuple)
    example: str = ""

    def field_map(self) -> dict[str, Field]:
        return {f.name: f for f in self.named_fields()}

    def named_fields(self) -> list[Field]:
        return list(self.fields)

    def required_fields(self) -> list[str]:
        return [f.name for f in self.fields if f.required]

    def to_schema(self) -> dict[str, Any]:
        props = {f.name: f.to_schema() for f in self.fields}
        return {
            "type": "object",
            "description": self.summary,
            "required": [f.name for f in self.fields if f.required],
            "properties": props,
            "additionalProperties": False,
        }


def _f(name: str, kind: str, description: str, **kw: Any) -> Field:
    """Field constructor — keeps the name attached to the field."""
    return Field(name=name, kind=kind, description=description, **kw)


# ── Shared field definitions ───────────────────────────────────────────────

_F_CONTEXT = _f(
    "context",
    TEXT,
    "Short label shown in the frozen header (top-left slide-index menu) for this slide.",
    example="The diagnosis",
)
_F_TITLE = _f(
    "title",
    RICHTEXT,
    "Slide heading. Newlines fold — the browser wraps with balanced line breaks. "
    "Use an explicit '|' if you need a hard break.",
    required=True,
    example="Most LMSs are built for management.|Learning deserves its own architect.",
)
_F_EYEBROW = _f(
    "eyebrow",
    TEXT,
    "Small label above the title, followed by a short rule.",
    example="The diagnosis",
)
_F_LEDE = _f(
    "lede",
    RICHTEXT,
    "Lead paragraph. Newlines fold into natural prose.",
    example="Most learning platforms are digital filing cabinets.",
)
_F_FOOT = _f(
    "foot",
    TEXT,
    "Footer line for this slide. Falls back to deck.footer.default.",
    example="Guidance through the storm",
)
_F_GRID_MT = _f(
    "grid_mt",
    INT,
    "Optional margin-top override (px) for the card/figure grid. Use it when a "
    "grid collides with the heading.",
    example=34,
)
_F_NOTE = _f(
    "note",
    LINES,
    "Optional mono block under the content. Newlines are preserved as line breaks.",
    example="Every learner is different.",
)
_F_STATS = _f(
    "stats",
    STATS,
    "Row of figure + caption pairs.",
    max_items=4,
    example='[{big: "3", small: "Focus areas"}, {big: "Day 1", small: "Starts building"}]',
)
_F_CARDS = _f(
    "cards",
    CARDS,
    "Cards, each with an optional kicker (k), a heading (h) and body prose (p).",
    max_items=8,
    example='[{k: "The incumbent", h: "Built for admins", p: "Proctored rows…"}]',
)
_F_FIGURE = _f(
    "figure",
    HTML,
    "Figure placed in the layout's media slot — typically inline SVG.",
    example="<svg viewBox='0 0 100 100'>…</svg>",
)
_F_FIGURE_ASSET = _f(
    "figure_asset",
    ASSET,
    "Path to an SVG or raster to inline into the media slot. Preferred over "
    "'figure' for anything large — it keeps deck payloads small.",
    example="assets/chart.svg",
)


# ── Layout registry ─────────────────────────────────────────────────────────

LAYOUTS: dict[str, Layout] = {
    "opener": Layout(
        name="opener",
        summary=(
            "Opening slide. Eyebrow, a large title, a lead paragraph and a row of "
            "figures. Use it for slide 1 — optionally once more to close a section."
        ),
        fields=(
            _F_EYEBROW,
            _F_TITLE,
            _F_LEDE,
            _F_STATS,
            _F_NOTE,
            _F_FOOT,
            _F_CONTEXT,
        ),
        example="""
- layout: opener
  context: Intent · Purpose · Vision
  eyebrow: An AI-native LMS
  title: Guidance through the storm.
  lede: Most learning platforms are digital filing cabinets…
  stats:
    - {big: "3", small: "Focus areas"}
    - {big: Day 1, small: "Your second brain starts building"}
  foot: St. Elmo's fire · the blue-white corona at the masthead
""",
    ),
    "cards2": Layout(
        name="cards2",
        summary=(
            "Title plus two equal-height cards. Use it to set two things against "
            "each other — the incumbent and the correction."
        ),
        fields=(
            _F_EYEBROW,
            _F_TITLE,
            _F_CARDS,
            _F_NOTE,
            _F_STATS,
            _F_FOOT,
            _F_CONTEXT,
            _F_GRID_MT,
        ),
        example="""
- layout: cards2
  context: Why we built it
  title: Most LMSs are designed for management.|Learning deserves its own architect.
  cards:
    - {k: The incumbent, h: Designed for administrators, p: Proctored rows…}
    - {k: The correction, h: Designed for the learner, p: Elms inverts…}
  note:
    - Every learner is different.
""",
    ),
    "cards3": Layout(
        name="cards3",
        summary=(
            "Title plus three equal-height cards. Use it for a triad — three "
            "focus areas, three stages, three options."
        ),
        fields=(
            _F_EYEBROW,
            _F_TITLE,
            _F_CARDS,
            _F_NOTE,
            _F_STATS,
            _F_FOOT,
            _F_CONTEXT,
            _F_GRID_MT,
        ),
        example="""
- layout: cards3
  context: Three focus areas
  title: What the learner actually needs.
  cards:
    - {k: Friend, h: Company, p: Presence before instruction…}
    - {k: Philosopher, h: Direction, p: Meaning behind the task…}
    - {k: Guide, h: Direction, p: A path that adapts…}
  lede_after: Each one compounds.
""",
    ),
    "figure2": Layout(
        name="figure2",
        summary=(
            "Title plus a two-column split: media on the left, prose on the right. "
            "The workhorse layout for diagrams and process stories."
        ),
        fields=(
            _F_EYEBROW,
            _F_TITLE,
            _F_FIGURE,
            _F_FIGURE_ASSET,
            _F_LEDE,
            _F_STATS,
            _F_FOOT,
            _F_CONTEXT,
            _F_GRID_MT,
        ),
        example="""
- layout: figure2
  context: How it works
  title: Compilers do not have to be black boxes.
  figure: "<svg viewBox='0 0 400 240'>…</svg>"
  lede: Eight stages, each one inspectable.
  lede2:
    - 1 · Read the obverse
    - 2 · Split the palette
  stats:
    - {big: "8", small: visible stages}
""",
    ),
    "closer": Layout(
        name="closer",
        summary=(
            "Closing slide. Eyebrow, title and two lead paragraphs. Use it to land "
            "the argument at the end of the deck."
        ),
        fields=(
            _F_EYEBROW,
            _F_TITLE,
            _F_LEDE,
            _F_FOOT,
            _F_CONTEXT,
        ),
        example="""
- layout: closer
  context: The invitation
  eyebrow: Where this goes next
  title: A second brain that starts on day one.
  lede: Every learner is different.
  lede2: The system starts there.
""",
    ),
    "demo": Layout(
        name="demo",
        summary=(
            "Centred hero layout holding a media frame — typically a <video> "
            "element. Built for the standalone demo page."
        ),
        fields=(
            _F_EYEBROW,
            _F_TITLE,
            _F_FIGURE,
            _F_FIGURE_ASSET,
            _F_LEDE,
            _F_FOOT,
            _F_CONTEXT,
        ),
        example="""
- layout: demo
  context: Demonstration
  eyebrow: A working demonstration
  title: See it in action.
  figure: "<video controls preload='metadata'><source src='demo.mp4' type='video/mp4'></video>"
  lede: A short walkthrough of the working mechanism.
""",
    ),
}

# Fields that may appear on any slide, regardless of layout.
COMMON_FIELDS: tuple[Field, ...] = (
    _F_CONTEXT,
    _F_FOOT,
    _F_GRID_MT,
)

# Extra fields the renderer understands but the layouts above do not all list.
EXTRA_SLIDE_FIELDS: tuple[Field, ...] = (
    _f("lede2", LINES, "Second lead block. On figure2 it renders as a preserved list."),
    _f("lede_after", RICHTEXT, "Paragraph rendered after the card grid (cards2, cards3)."),
)

DECK_FIELD_DOCS: dict[str, str] = {
    "deck": "Settings shared by every slide (title, brand, footer, nav).",
    "theme": "Named theme from themes/*.theme.yaml. Defaults to 'mariners-chart'.",
    "slides": "The slides, in order. The first slide is the opening slide.",
}

AUTHORING_NOTES = [
    "Deck-level keys: `deck` (title, brand, footer, nav), `theme`, `slides`.",
    "`deck.brand.mark` is a path to an SVG in the workspace; `deck.brand.word` "
    "supports **bold** segments.",
    "Titles fold their newlines and wrap with balanced breaks. Use '|' for an explicit break.",
    "`note` and `stat.small` keep their line breaks; `lede`/`lede_after`/`card.p` fold.",
    "Inline **bold**, *italic* and `code` work in every text field.",
    "`figure` is raw HTML and passes through untouched. `figure_asset` inlines a "
    "file from the workspace instead — prefer it for anything over a few KB.",
    "Every slide needs a `layout`. Titles are required on all layouts.",
    "Cards: `cards2` shows the first two cards, `cards3` the first three.",
    "`deck.chrome: false` removes the site header and nav for a standalone deck.",
    "`deck.webfonts: false` drops the Google Fonts links so the deck is fully offline.",
]


# ── Public helpers ─────────────────────────────────────────────────────────


def layout_names() -> list[str]:
    return list(LAYOUTS.keys())


def layout_catalog() -> list[dict[str, Any]]:
    """Human- and LLM-readable description of every layout."""
    out = []
    for name, lay in LAYOUTS.items():
        out.append(
            {
                "layout": name,
                "summary": lay.summary,
                "required_fields": lay.required_fields(),
                "fields": {
                    f.name: {
                        "kind": f.kind,
                        "description": f.description,
                        **({"max_items": f.max_items} if f.max_items is not None else {}),
                        **({"example": f.example} if f.example else {}),
                    }
                    for f in lay.fields
                },
                "example_yaml": lay.example.strip(),
            }
        )
    return out


def layout_schema(name: str) -> dict[str, Any]:
    """Strict per-layout JSON Schema."""
    lay = LAYOUTS.get(name)
    if lay is None:
        raise KeyError(name)
    schema = lay.to_schema()
    schema["properties"]["layout"] = {"const": name, "type": "string"}
    return schema


def slide_schema() -> dict[str, Any]:
    """Flat slide schema — safe to hand to a function-calling LLM.

    Deliberately flat (no ``oneOf``): several tool-calling runtimes flatten
    JSON Schema poorly, and per-layout strictness is enforced by the validator
    and published separately by :func:`layout_schema`.
    """
    props: dict[str, Any] = {
        "layout": {
            "type": "string",
            "enum": layout_names(),
            "description": "Slide layout. See the layout catalog for what each one shows.",
        }
    }
    for f in COMMON_FIELDS:
        props[f.name] = f.to_schema()
    for f in EXTRA_SLIDE_FIELDS:
        props[f.name] = f.to_schema()
    for lay in LAYOUTS.values():
        for f in lay.fields:
            if f.name not in props:
                props[f.name] = f.to_schema()
    return {
        "type": "object",
        "required": ["layout", "title"],
        "properties": props,
        "additionalProperties": True,
    }


def deck_json_schema() -> dict[str, Any]:
    """JSON Schema for a whole deck — the contract an LLM writes against."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://helmsmate.local/schemas/deck-1.0.json",
        "title": "HelmsMate deck",
        "description": (
            "A HelmsMate deck: deck-level settings, a named theme and an ordered "
            "list of slides. Build it with the build_deck tool."
        ),
        "type": "object",
        "required": ["slides"],
        "additionalProperties": False,
        "properties": {
            "deck": {
                "type": "object",
                "description": "Settings shared by every slide.",
                "properties": {
                    "title": {"type": "string", "description": "Document title and browser tab."},
                    "brand": {
                        "type": "object",
                        "description": "The brand lockup in the frozen header.",
                        "properties": {
                            "mark": {
                                "type": "string",
                                "description": "Path to an SVG in the workspace; inlined at build.",
                            },
                            "word": {
                                "type": "string",
                                "description": "Wordmark. **bold** segments are supported.",
                            },
                            "alt": {"type": "string", "description": "Alt text for the mark."},
                        },
                    },
                    "footer": {
                        "type": "object",
                        "properties": {
                            "default": {"type": "string", "description": "Default footer line."}
                        },
                    },
                    "nav": {
                        "type": "object",
                        "properties": {
                            "style": {"type": "string", "enum": ["pill", "plain"]},
                            "dots": {"type": "boolean"},
                            "progress": {"type": "boolean"},
                        },
                    },
                },
            },
            "theme": {
                "type": "string",
                "description": "Named theme from themes/*.theme.yaml.",
                "default": "mariners-chart",
            },
            "slides": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/slide"},
            },
        },
        "$defs": {"slide": slide_schema()},
    }


def schema_document() -> dict[str, Any]:
    """Everything a client needs to author a deck, in one document."""
    return {
        "schema_version": SCHEMA_VERSION,
        "description": (
            "HelmsMate turns one YAML deck into a single self-contained HTML "
            "presentation. Author a deck against this contract, then call "
            "build_deck to get the finished presentation."
        ),
        "deck_schema": deck_json_schema(),
        "layouts": layout_catalog(),
        "authoring_notes": AUTHORING_NOTES,
        "conventions": {
            "text_kinds": {
                TEXT: "one line, newlines fold",
                LINES: "newlines preserved as <br>",
                RICHTEXT: "newlines fold into prose",
                HTML: "raw HTML, passed through",
                ASSET: "path to a workspace file, inlined at build",
            }
        },
    }


def schema_json(indent: int | None = 2) -> str:
    return json.dumps(schema_document(), indent=indent)


def _resolve_refs(node: Any, defs: dict[str, Any]) -> Any:
    """Replace ``#/$defs/...`` references with the definition itself."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            target = defs.get(ref.split("/")[-1], {})
            resolved = _resolve_refs(target, defs)
            extra = {k: _resolve_refs(v, defs) for k, v in node.items() if k != "$ref"}
            return {**resolved, **extra}
        return {k: _resolve_refs(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(v, defs) for v in node]
    return node


def inline_deck_schema() -> dict[str, Any]:
    """The deck schema with every ``$ref`` resolved.

    Tool input schemas are embedded inside a larger schema, where a dangling
    ``#/$defs/slide`` would resolve against the wrong root. Inlining keeps a
    tool schema self-contained — it can be handed to any client verbatim.
    """
    schema = deck_json_schema()
    defs = schema.get("$defs", {})
    resolved = _resolve_refs(schema, defs)
    resolved.pop("$defs", None)
    return resolved
