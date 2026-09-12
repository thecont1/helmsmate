#!/usr/bin/env python3
"""HelmChart build step.

Reads deck.yaml, a named theme, and the generic HTML template, then writes a
single self-contained index.html with zero runtime dependencies.

Usage:
    python engine/build.py
    python engine/build.py path/to/deck.yaml
"""

import argparse
import base64
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    print("HelmChart build requires PyYAML. Install: uv add pyyaml", file=sys.stderr)
    raise

REPO = Path(__file__).resolve().parent.parent
THEMES_DIR = REPO / "themes"
TEMPLATE_FILE = REPO / "engine" / "template.html"
DIST_FILE = REPO / "dist" / "index.html"


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def bold(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text or "")


def br(text: str) -> str:
    return "<br>".join(line for line in (text or "").splitlines())


def prose(text: str) -> str:
    """Folded/paragraph text: collapse newlines, then bold-ify."""
    if not text:
        return ""
    return bold(" ".join(text.split()))


def css_vars_from_theme(theme: dict) -> str:
    """Flatten the theme YAML into CSS custom properties."""
    lines = ["/* theme variables */"]

    def walk(prefix: str, node):
        if isinstance(node, dict):
            for k, v in node.items():
                key = f"{prefix}-{k}" if prefix else k
                walk(key, v)
        elif isinstance(node, list):
            value = ", ".join(str(i) for i in node)
            lines.append(f"  --{prefix}: {value};")
        else:
            lines.append(f"  --{prefix}: {node};")

    walk("", theme)
    return "\n".join(f"  {l}" if not l.startswith("/*") else l for l in lines)


def inline_svg(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def svg_to_data_uri(svg: str) -> str:
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def card_html(card: dict) -> str:
    return f"""<div class="card">
  <div class="k">{bold(card.get("k", ""))}</div>
  <h3>{bold(card.get("h", ""))}</h3>
  <p>{prose(card.get("p", ""))}</p>
</div>"""


def stat_html(stat: dict) -> str:
    return f"""<div class="stat">
  <div class="big">{bold(str(stat.get("big", "")))}</div>
  <div class="small">{br(stat.get("small", ""))}</div>
</div>"""


def slide_html(slide: dict, index: int, total: int, foot_default: str) -> str:
    layout = slide.get("layout", "opener")
    context = slide.get("context", "")
    eyebrow = bold(slide.get("eyebrow", ""))
    title = bold(br(slide.get("title", "")))
    lede = prose(slide.get("lede", ""))
    lede2 = prose(slide.get("lede2", ""))
    note = br(slide.get("note", ""))
    figure = slide.get("figure", "")
    cards = slide.get("cards", [])
    stats = slide.get("stats", [])
    foot = slide.get("foot", foot_default)

    body = ""

    if layout == "opener":
        stats_html = "".join(stat_html(s) for s in stats)
        body = f"""<p class="eyebrow">{eyebrow}</p>
<h2>{title}</h2>
<p class="lede">{lede}</p>
<div class="statline">{stats_html}</div>"""
        if note:
            body += f'\n<div class="note">{note}</div>'

    elif layout == "cards2":
        cards_html = "".join(card_html(c) for c in cards[:2])
        stats_html = "".join(stat_html(s) for s in stats)
        note_html = f'\n<div class="note">{note}</div>' if note else ""
        body = f"""<p class="eyebrow">{eyebrow}</p>
<h2>{title}</h2>
<div class="grid2">{cards_html}</div>{note_html}
<div class="statline">{stats_html}</div>"""

    elif layout == "cards3":
        cards_html = "".join(card_html(c) for c in cards[:3])
        body = f"""<p class="eyebrow">{eyebrow}</p>
<h2>{title}</h2>
<div class="grid3">{cards_html}</div>
<p class="lede_after">{prose(slide.get("lede_after", ""))}</p>"""

    elif layout == "figure2":
        stats_html = "".join(stat_html(s) for s in stats)
        body = f"""<p class="eyebrow">{eyebrow}</p>
<h2>{title}</h2>
<div class="figure2-stage">
  <div class="figure-wrap">{figure}</div>
  <div>
    <p class="lede">{lede}</p>
    <div class="statline">{stats_html}</div>
    <p class="lede2">{lede2}</p>
  </div>
</div>"""

    elif layout == "closer":
        lede2_html = f'<p class="lede2">{lede2}</p>' if lede2 else ""
        body = f"""<p class="eyebrow">{eyebrow}</p>
<h2>{title}</h2>
<p class="lede">{lede}</p>
{lede2_html}"""

    else:
        raise ValueError(f"Unknown layout: {layout}")

    return f"""<section class="slide {layout}" data-context="{context}" data-layout="{layout}" role="listitem" aria-label="Slide {index}">
  <div class="stage">
{body}
  </div>
  <div class="stage-foot">
    <span class="foot-text">{foot}</span>
    <div class="nav" aria-label="Slide {index} navigation">
      <button class="prev" aria-label="Previous slide" type="button">&#8249;</button>
      <span class="count">{index} / {total}</span>
      <button class="next" aria-label="Next slide" type="button">&#8250;</button>
    </div>
  </div>
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
    reset_on_click = brand.get("reset_on_click", False)

    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = f.read()

    slides = deck.get("slides", [])
    total = len(slides)
    foot_default = deck.get("deck", {}).get("footer", {}).get("default", "")

    first_context = slides[0].get("context", "") if slides else ""

    slides_html = "\n".join(
        slide_html(slide, i + 1, total, foot_default) for i, slide in enumerate(slides)
    )

    output = template
    output = output.replace("{{DECK_TITLE}}", deck.get("deck", {}).get("title", "HelmChart"))
    output = output.replace("{{FAVICON}}", favicon)
    output = output.replace("{{THEME_VARS}}", css_vars_from_theme(theme))
    output = output.replace("{{LOGO_SVG}}", logo_svg)
    output = output.replace("{{BRAND_WORD}}", brand_word)
    output = output.replace("{{BRAND_ALT}}", brand_alt)
    output = output.replace("{{FIRST_CONTEXT}}", first_context)
    output = output.replace("{{SLIDE_COUNT}}", str(total))
    output = output.replace("{{SLIDES}}", slides_html)

    # Logo click is always wired; use brand.reset_on_click: false in the
    # future if you want a non-interactive mark (href still links to #/1).

    DIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DIST_FILE, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Built {DIST_FILE} ({len(output):,} bytes) from {deck_path.name}")
    return DIST_FILE


def main() -> None:
    parser = argparse.ArgumentParser(description="HelmChart deck builder")
    parser.add_argument("deck", nargs="?", default=str(REPO / "deck.example.yaml"), help="Path to deck YAML")
    args = parser.parse_args()

    deck_path = Path(args.deck)
    if not deck_path.is_absolute():
        deck_path = REPO / deck_path

    build(deck_path)


if __name__ == "__main__":
    main()
