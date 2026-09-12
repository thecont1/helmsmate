#!/usr/bin/env python3
"""HelmsMate build step.

Reads deck.yaml, a named theme, and the generic HTML template, then writes a
single self-contained index.html with zero runtime dependencies.

Usage:
    python engine/build.py
    python engine/build.py path/to/deck.yaml

Authoring conventions:
    title : newlines fold — the browser wraps titles (text-wrap:balance)
    note / stat.small : literal newlines render as <br>
    lede / lede2 / lede_after / card.p : newlines fold into natural prose
    **text** renders <b>text</b> in any text field
    figure : raw HTML (SVG), passed through untouched
    grid_mt : optional integer px margin-top override for the card/figure grid
"""

import argparse
import base64
import html
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("HelmsMate build requires PyYAML. Install: uv add pyyaml", file=sys.stderr)
    raise

REPO = Path(__file__).resolve().parent.parent
THEMES_DIR = REPO / "themes"
TEMPLATE_FILE = REPO / "engine" / "template.html"
DIST_FILE = REPO / "dist" / "index.html"


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def esc(text: str) -> str:
    return html.escape(str(text or ""), quote=False)


def bold(text: str) -> str:
    """Escape, then promote **x** to <b>."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(text))


def br(text: str) -> str:
    """Line-owned text: each line escaped, joined with <br>."""
    return "<br>".join(bold(line) for line in (text or "").splitlines())


def prose(text: str) -> str:
    """Folded text: collapse newlines, escape, then bold-ify."""
    return bold(" ".join((text or "").split()))


def attr(text: str) -> str:
    return html.escape(str(text or ""), quote=True)


def css_vars_from_theme(theme: dict) -> str:
    """Flatten theme YAML into CSS custom properties.

    Mapping:  colors.beacon.50 → --beacon-50,  fonts.display → --font-display,
              effects.grid_glow → --grid-glow.  The `name` key is metadata only.
    """
    lines = []

    def walk(path, node):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(path + [k], v)
        else:
            if path == ["name"]:
                return
            parts = [p for p in path if p not in ("colors", "effects")]
            if parts and parts[0] == "fonts":
                parts[0] = "font"
            var = "-".join(str(p) for p in parts).replace("_", "-")
            lines.append(f"  --{var}: {node};")

    walk([], theme)
    return "\n".join(lines)


def inline_svg(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        svg = f.read().strip()
    # Template styles target svg.corona; inject the class if the asset lacks it.
    if 'class="corona"' not in svg:
        svg = re.sub(r"<svg\b", '<svg class="corona"', svg, count=1)
    return svg


def svg_to_data_uri(svg: str) -> str:
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def card_html(card: dict) -> str:
    k = esc(card.get("k", "")).replace("◦ ", "◦&nbsp;")
    return f"""<div class="card">
        <span class="k">{k}</span>
        <h3>{bold(card.get("h", ""))}</h3>
        <p>{prose(card.get("p", ""))}</p>
      </div>"""


def stat_html(stat: dict) -> str:
    return f'<div class="stat"><b>{bold(stat.get("big", ""))}</b><span>{br(stat.get("small", ""))}</span></div>'


def grid_mt_attr(slide: dict) -> str:
    v = slide.get("grid_mt")
    return f' style="margin-top:{int(v)}px"' if v is not None else ""


def slide_html(slide: dict, index: int, total: int, foot_default: str) -> str:
    layout = slide.get("layout", "opener")
    context = attr(slide.get("context", ""))
    eyebrow = bold(slide.get("eyebrow", ""))
    title = prose(slide.get("title", ""))
    lede = prose(slide.get("lede", ""))
    lede2 = prose(slide.get("lede2", ""))
    note = br(slide.get("note", ""))
    figure = slide.get("figure", "")
    cards = slide.get("cards", [])
    stats = slide.get("stats", [])
    foot = esc(slide.get("foot", foot_default))
    gmt = grid_mt_attr(slide)

    body = ""

    if layout == "opener":
        stats_html = "".join(stat_html(s) for s in stats)
        body = f"""<p class="eyebrow">{eyebrow}</p>
    <h1>{title}</h1>
    <p class="lede">
      {lede}
    </p>
    <div class="stats">
      {stats_html}
    </div>"""
        if note:
            body += f'\n    <p class="lede note">{note}</p>'

    elif layout == "cards2":
        cards_html = "".join(card_html(c) for c in cards[:2])
        note_html = f'\n    <p class="lede note">\n      {note}\n    </p>' if note else ""
        stats_html = f'\n    <div class="stats stats-tight">{"".join(stat_html(s) for s in stats)}</div>' if stats else ""
        body = f"""<p class="eyebrow">{eyebrow}</p>
    <h2>{title}</h2>
    <div class="grid2"{gmt}>
      {cards_html}
    </div>{note_html}{stats_html}"""

    elif layout == "cards3":
        cards_html = "".join(card_html(c) for c in cards[:3])
        lede_after = prose(slide.get("lede_after", ""))
        lede_after_html = f'\n    <p class="lede lede-after">\n      {lede_after}\n    </p>' if lede_after else ""
        body = f"""<p class="eyebrow">{eyebrow}</p>
    <h2>{title}</h2>
    <div class="grid3"{gmt}>
      {cards_html}
    </div>{lede_after_html}"""

    elif layout == "figure2":
        stats_html = "".join(stat_html(s) for s in stats)
        lede2_html = f'\n        <p class="lede lede2">\n          {lede2}\n        </p>' if lede2 else ""
        body = f"""<p class="eyebrow">{eyebrow}</p>
    <h2>{title}</h2>
    <div class="grid2"{gmt}>
      <div class="figure">
        {figure}
      </div>
      <div>
        <p class="lede lede-flush">
          {lede}
        </p>
        <div class="stats stats-tight">
          {stats_html}
        </div>{lede2_html}
      </div>
    </div>"""

    elif layout == "closer":
        lede2_html = f'\n    <p class="lede lede-followup">\n      {lede2}\n    </p>' if lede2 else ""
        body = f"""<p class="eyebrow">{eyebrow}</p>
    <h2>
      {title}
    </h2>
    <p class="lede">
      {lede}
    </p>{lede2_html}"""

    else:
        raise ValueError(f"Unknown layout: {layout}")

    return f"""<section class="slide" data-context="{context}">
  <div class="stage">
    {body}
  </div>
  <footer class="foot">
    <span>{foot}</span>
  </footer>
</section>"""


def build(deck_path: Path) -> Path:
    deck = load_yaml(deck_path)
    theme_name = deck.get("theme", "mariners-chart")
    theme = load_yaml(THEMES_DIR / f"{theme_name}.theme.yaml")

    brand = deck.get("deck", {}).get("brand", {})
    logo_path = REPO / brand.get("mark", "")
    logo_svg = inline_svg(logo_path)
    favicon = svg_to_data_uri(logo_svg)

    brand_word = bold(brand.get("word", ""))
    brand_alt = brand.get("alt", "Brand mark")

    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = f.read()

    slides = deck.get("slides", [])
    total = len(slides)
    foot_default = deck.get("deck", {}).get("footer", {}).get("default", "")

    slides_html = "\n\n".join(
        slide_html(slide, i + 1, total, foot_default) for i, slide in enumerate(slides)
    )

    output = template
    output = output.replace("{{DECK_TITLE}}", esc(deck.get("deck", {}).get("title", "HelmsMate")))
    output = output.replace("{{FAVICON}}", favicon)
    output = output.replace("/*{{THEME_VARS}}*/", css_vars_from_theme(theme))
    output = output.replace("{{LOGO_SVG}}", logo_svg)
    output = output.replace("{{BRAND_WORD}}", brand_word)
    output = output.replace("{{BRAND_ALT}}", brand_alt)
    output = output.replace("{{SLIDE_COUNT}}", str(total))
    output = output.replace("{{SLIDES}}", slides_html)

    DIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DIST_FILE, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Built {DIST_FILE} ({len(output):,} bytes) from {deck_path.name}")
    return DIST_FILE


def main() -> None:
    parser = argparse.ArgumentParser(description="HelmsMate deck builder")
    parser.add_argument("deck", nargs="?", default=str(REPO / "deck.example.yaml"), help="Path to deck YAML")
    args = parser.parse_args()

    deck_path = Path(args.deck)
    if not deck_path.is_absolute():
        deck_path = REPO / deck_path

    build(deck_path)


if __name__ == "__main__":
    main()
