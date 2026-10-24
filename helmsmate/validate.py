"""Validation — check a deck against the contract in :mod:`helmsmate.spec`.

Every problem carries a path (``slides[3].cards[1].h``), a message, and a hint.
The hint matters: this validation exists to be read by an LLM that will
author the next version of the deck, so the errors have to say what to do
rather than only what is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from . import spec, themes

ERROR = "error"
WARNING = "warning"


@dataclass
class ValidationIssue:
    """One problem found in a deck."""

    path: str
    message: str
    hint: str = ""
    severity: str = ERROR

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        base = f"{self.path}: {self.message}"
        return f"{base} — {self.hint}" if self.hint else base


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_texty(value: Any) -> bool:
    """Text fields accept a string or a list of lines."""
    if isinstance(value, str):
        return True
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def validate_deck(
    deck: Any,
    *,
    themes_dir: Any = None,
    known_themes: list[str] | None = None,
) -> list[ValidationIssue]:
    """Validate a deck. Returns problems, empty list when the deck is sound."""
    issues: list[ValidationIssue] = []

    def err(path: str, message: str, hint: str = "") -> None:
        issues.append(ValidationIssue(path, message, hint, ERROR))

    def warn(path: str, message: str, hint: str = "") -> None:
        issues.append(ValidationIssue(path, message, hint, WARNING))

    if not isinstance(deck, dict):
        err("", "Deck must be a mapping with 'deck', 'theme' and 'slides'.",
            "Start from GET /api/schema and copy the example deck.")
        return issues

    # ── deck level ─────────────────────────────────────────────────────────
    for key in deck:
        if key not in ("deck", "theme", "slides"):
            err(key, f"Unknown top-level key '{key}'.",
                "Only 'deck', 'theme' and 'slides' are allowed at the top level.")

    theme_name = deck.get("theme", themes.DEFAULT_THEME)
    if not _is_str(theme_name):
        err("theme", "Theme name must be a string.", f"Try one of: {', '.join(spec.layout_names())}")
    else:
        available = known_themes if known_themes is not None else themes.list_theme_names(themes_dir)
        if theme_name not in available:
            err("theme", f"Unknown theme '{theme_name}'.",
                f"Available themes: {', '.join(available) or '(none found)'}.")

    deck_cfg = deck.get("deck", {})
    if deck_cfg is not None and not isinstance(deck_cfg, dict):
        err("deck", "'deck' must be a mapping.", "Use deck: {title: ..., brand: {...}}.")
        deck_cfg = {}
    deck_cfg = deck_cfg or {}

    brand = deck_cfg.get("brand", {}) or {}
    if not isinstance(brand, dict):
        err("deck.brand", "'brand' must be a mapping.", "Use brand: {mark: ..., word: ...}.")
        brand = {}

    if not _is_str(deck_cfg.get("title", "")):
        err("deck.title", "Deck title must be a string.", "It becomes the browser tab title.")

    mark = brand.get("mark")
    if mark is not None and not _is_str(mark):
        err("deck.brand.mark", "Brand mark must be a path to an SVG file.",
            "For example: assets/sef-corona.svg")
    elif isinstance(mark, str) and not mark.lower().endswith((".svg", ".png", ".jpg", ".jpeg")):
        warn("deck.brand.mark", f"Brand mark '{mark}' is not a typical image file.",
             "An SVG is best — it is inlined as markup and inherits theme colours.")

    footer = deck_cfg.get("footer", {}) or {}
    if not isinstance(footer, dict):
        err("deck.footer", "'footer' must be a mapping.", "Use footer: {default: ...}.")
    elif "default" in footer and not _is_texty(footer["default"]):
        err("deck.footer.default", "Footer default must be a string.",
            "It is the fallback footer line for slides that do not set 'foot'.")

    chrome = deck_cfg.get("chrome", True)
    if isinstance(chrome, dict):
        for key in ("word", "home_url", "home_label"):
            if key in chrome and not _is_str(chrome[key]):
                err(f"deck.chrome.{key}", f"chrome.{key} must be a string.", "")
    elif not isinstance(chrome, bool):
        err("deck.chrome", "'chrome' must be true, false, or a mapping.",
            "false removes the site header and nav for a standalone deck.")

    # ── slides ─────────────────────────────────────────────────────────────
    slides = deck.get("slides")
    if slides is None:
        err("slides", "'slides' is required.", "A deck needs at least one slide.")
        return issues
    if not isinstance(slides, list):
        err("slides", "'slides' must be a list.", "Each entry is one slide mapping.")
        return issues
    if not slides:
        err("slides", "A deck needs at least one slide.",
            "The first slide is the opening slide — try layout 'opener'.")
        return issues

    for i, slide in enumerate(slides):
        p = f"slides[{i}]"
        if not isinstance(slide, dict):
            err(p, "Each slide must be a mapping.", "")
            continue

        layout = slide.get("layout")
        if layout is None:
            err(f"{p}.layout", "Every slide needs a layout.",
                f"One of: {', '.join(spec.layout_names())}.")
            continue
        if not isinstance(layout, str) or layout not in spec.LAYOUTS:
            err(f"{p}.layout", f"Unknown layout {layout!r}.",
                f"One of: {', '.join(spec.layout_names())}.")
            continue

        lay = spec.LAYOUTS[layout]

        # Required fields for this layout.
        for fname in lay.required_fields():
            if fname not in slide or slide.get(fname) in (None, ""):
                err(f"{p}.{fname}", f"'{fname}' is required by the '{layout}' layout.",
                    f"See GET /api/layouts for the '{layout}' example.")

        # Shared field types.
        for fname in ("title", "context", "foot", "eyebrow"):
            if fname in slide and not _is_texty(slide[fname]):
                err(f"{p}.{fname}", f"'{fname}' must be a string.",
                    "Text fields accept a single string or a list of lines.")
        for fname in ("lede", "lede_after"):
            if fname in slide and not _is_texty(slide[fname]):
                err(f"{p}.{fname}", f"'{fname}' must be a string.", "")
        if "note" in slide and not _is_texty(slide["note"]):
            err(f"{p}.note", "'note' must be a string or a list of lines.", "")
        if "grid_mt" in slide and not isinstance(slide["grid_mt"], int):
            err(f"{p}.grid_mt", "'grid_mt' must be an integer number of pixels.", "")
        if "lede2" in slide and not _is_texty(slide["lede2"]):
            err(f"{p}.lede2", "'lede2' must be a string or a list of lines.", "")

        # Cards.
        cards = slide.get("cards")
        if cards is not None:
            if not isinstance(cards, list):
                err(f"{p}.cards", "'cards' must be a list.", "")
            else:
                want = 2 if layout == "cards2" else 3
                if layout in ("cards2", "cards3") and len(cards) != want:
                    warn(f"{p}.cards", f"The '{layout}' layout shows {want} cards; {len(cards)} given.",
                         f"Give exactly {want} cards for an even row.")
                for j, card in enumerate(cards):
                    if not isinstance(card, dict):
                        err(f"{p}.cards[{j}]", "Each card must be a mapping with 'h' (heading).", "")
                        continue
                    if not card.get("h"):
                        err(f"{p}.cards[{j}].h", "Card heading 'h' is required.", "")
                    for key in ("k", "h", "p"):
                        if key in card and not _is_texty(card[key]):
                            err(f"{p}.cards[{j}].{key}", f"Card '{key}' must be a string.", "")

        # Stats.
        stats = slide.get("stats")
        if stats is not None:
            if not isinstance(stats, list):
                err(f"{p}.stats", "'stats' must be a list of {big, small} pairs.", "")
            else:
                for j, stat in enumerate(stats):
                    if not isinstance(stat, dict):
                        err(f"{p}.stats[{j}]", "Each stat must be a mapping with 'big' and 'small'.", "")
                        continue
                    if not stat.get("big"):
                        err(f"{p}.stats[{j}].big", "Stat 'big' is required.", "")
                    if "small" in stat and not _is_texty(stat["small"]):
                        err(f"{p}.stats[{j}].small", "Stat 'small' must be a string.", "")

        # Media.
        figure = slide.get("figure")
        figure_asset = slide.get("figure_asset")
        if figure is not None and not _is_str(figure):
            err(f"{p}.figure", "'figure' must be a string of raw HTML/SVG.", "")
        if figure_asset is not None and not _is_str(figure_asset):
            err(f"{p}.figure_asset", "'figure_asset' must be a path to an image file.", "")
        if layout in ("figure2", "demo") and not figure and not figure_asset:
            warn(f"{p}.figure", f"The '{layout}' layout has an empty media slot.",
                 "Set 'figure' (inline SVG) or 'figure_asset' (path to an image).")
        if figure and figure_asset:
            warn(f"{p}.figure_asset", "Both 'figure' and 'figure_asset' are set; 'figure' wins.",
                 "Remove one to avoid confusion.")

        # Unknown keys on a slide are usually typos from an LLM.
        allowed = {"layout"} | {f.name for f in lay.fields} | {
            "lede2", "lede_after", "note", "figure", "figure_asset", "stats", "cards",
        }
        for key in slide:
            if key not in allowed:
                warn(f"{p}.{key}", f"'{key}' is not used by the '{layout}' layout.",
                     "It will be ignored. Check the layout catalog for the right field name.")

    return issues


def is_valid(deck: Any, **kw: Any) -> bool:
    return not any(i.severity == ERROR for i in validate_deck(deck, **kw))
