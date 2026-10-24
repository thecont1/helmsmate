"""Renderer — a deck dict becomes one self-contained HTML file.

The rendering rules live here and nowhere else. :mod:`helmsmate.spec` describes
the contract; :mod:`helmsmate.validate` checks it; this module draws it.

Output is a single file: HTML + CSS + JS + inlined SVG. No runtime fetch, no
framework, no CDN unless the deck asks for webfonts.

Authoring conventions (mirrored in spec.py):

    title / lede / lede_after / card.p : newlines fold into prose
    note / stat.small / lede2          : newlines render as <br>
    **bold**, *italic*, `code`         : honoured in every text field
    figure                             : raw HTML, passed through untouched
    figure_asset                       : a workspace file, inlined at build time
    grid_mt                            : optional px margin-top for the grid
"""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import paths, themes


class BuildError(Exception):
    """Raised when a deck cannot be rendered."""


# ── Text helpers ───────────────────────────────────────────────────────────


def esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=False)


def bold(text: Any, code_names: Iterable[str] = ()) -> str:
    """Escape, promote **x** to <b>, *x* to <em>, `x` to <code>, then wrap brand names."""
    escaped = esc(as_text(text))
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    # Italics: process after bold so **x** is already consumed.
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    # Inline code: backticks. Single backtick runs; non-greedy.
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return _wrap_code_names(escaped, code_names)


def _wrap_code_names(html_text: str, code_names: Iterable[str]) -> str:
    """Render the named brand words in the mono face.

    Auto-wrapping keeps the rest of the inline styling (bold, italic) free to
    nest. Skips anything already inside a <code> element.
    """
    names = [n for n in (code_names or []) if n]
    if not names:
        return html_text
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", flags=re.IGNORECASE)

    out: list[str] = []
    for chunk in re.split(r"(<code>.*?</code>)", html_text, flags=re.DOTALL):
        if chunk.startswith("<code>"):
            out.append(chunk)
        else:
            out.append(pattern.sub(r"<code>\1</code>", chunk))
    return "".join(out)


def as_text(value: Any) -> str:
    """Flatten a text field to a string.

    Text fields accept either a string or a list of lines (the README shows
    ``note:`` as a list). Rendering the list's repr would leak Python syntax
    onto the slide, so lists are joined into lines here.
    """
    if isinstance(value, (list, tuple)):
        return "\n".join(str(v) for v in value)
    return "" if value is None else str(value)


def br(text: Any, code_names: Iterable[str] = ()) -> str:
    """Line-owned text: each line escaped, joined with <br>."""
    return "<br>".join(bold(line, code_names) for line in as_text(text).splitlines())


def prose(text: Any, code_names: Iterable[str] = ()) -> str:
    """Folded text: collapse newlines, escape, then inline-style."""
    return bold(" ".join(as_text(text).split()), code_names)


def title_text(text: Any, code_names: Iterable[str] = ()) -> str:
    """A slide title.

    Newlines fold — the browser wraps with balanced breaks. ``|`` marks an
    explicit break, because the engine never guesses where a title should
    stop. The README has promised this marker since v0.
    """
    parts = [prose(chunk, code_names) for chunk in as_text(text).split("|")]
    return "<br>".join(p for p in parts if p != "")


def attr(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


# ── Assets ─────────────────────────────────────────────────────────────────

RASTER_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
}


def read_svg(path: Path, add_corona_class: bool = True) -> str:
    """Read an SVG file as markup.

    Template styles target ``svg.corona``; inject the class if the asset lacks
    it (the brand mark's hook in the frozen header).
    """
    with open(path, "r", encoding="utf-8") as f:
        svg = f.read().strip()
    if add_corona_class and 'class="corona"' not in svg:
        svg = re.sub(r"<svg\b", '<svg class="corona"', svg, count=1)
    return svg


def svg_to_data_uri(svg: str) -> str:
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def asset_to_markup(path: Path) -> str:
    """Turn an asset file into markup that can sit in a figure slot.

    SVG is inlined as markup (crisp, and it inherits the theme's colours).
    Rasters become a data-URI ``<img>`` so the deck stays self-contained.
    """
    suffix = path.suffix.lower()
    if suffix == ".svg":
        return read_svg(path, add_corona_class=False)
    mime = RASTER_MIME.get(suffix)
    if not mime:
        raise BuildError(f"Unsupported asset type: {path.name}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<img src="data:{mime};base64,{encoded}" alt="">'


# ── Slide fragments ────────────────────────────────────────────────────────


def card_html(card: dict, code_names: Iterable[str] = ()) -> str:
    k = esc(card.get("k", "")).replace("◦ ", "◦&nbsp;")
    return f"""<div class="card">
        <span class="k">{k}</span>
        <h3>{bold(card.get("h", ""), code_names)}</h3>
        <p>{prose(card.get("p", ""), code_names)}</p>
      </div>"""


def stat_html(stat: dict, code_names: Iterable[str] = ()) -> str:
    return (
        f'<div class="stat"><b>{bold(stat.get("big", ""), code_names)}</b>'
        f'<span>{br(stat.get("small", ""), code_names)}</span></div>'
    )


def grid_mt_attr(slide: dict) -> str:
    v = slide.get("grid_mt")
    return f' style="margin-top:{int(v)}px"' if v is not None else ""


def slide_html(
    slide: dict,
    index: int,
    total: int,
    foot_default: str,
    code_names: Iterable[str] = (),
    figure_asset_html: str = "",
) -> str:
    layout = slide.get("layout", "opener")
    context = attr(slide.get("context", ""))
    eyebrow = bold(slide.get("eyebrow", ""), code_names)
    title = title_text(slide.get("title", ""), code_names)
    lede = prose(slide.get("lede", ""), code_names)
    lede2 = prose(slide.get("lede2", ""), code_names)
    note = br(slide.get("note", ""), code_names)
    figure = slide.get("figure", "") or figure_asset_html
    cards = slide.get("cards", []) or []
    stats = slide.get("stats", []) or []
    foot = bold(slide.get("foot", foot_default), code_names)
    gmt = grid_mt_attr(slide)

    body = ""

    if layout == "opener":
        stats_html = "".join(stat_html(s, code_names) for s in stats)
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
        cards_html = "".join(card_html(c, code_names) for c in cards[:2])
        note_html = f'\n    <p class="lede note">\n      {note}\n    </p>' if note else ""
        stats_html = (
            f'\n    <div class="stats stats-tight">{"".join(stat_html(s, code_names) for s in stats)}</div>'
            if stats
            else ""
        )
        body = f"""<p class="eyebrow">{eyebrow}</p>
    <h2>{title}</h2>
    <div class="grid2"{gmt}>
      {cards_html}
    </div>{note_html}{stats_html}"""

    elif layout == "cards3":
        cards_html = "".join(card_html(c, code_names) for c in cards[:3])
        lede_after = prose(slide.get("lede_after", ""), code_names)
        lede_after_html = f'\n    <p class="lede lede-after">\n      {lede_after}\n    </p>' if lede_after else ""
        body = f"""<p class="eyebrow">{eyebrow}</p>
    <h2>{title}</h2>
    <div class="grid3"{gmt}>
      {cards_html}
    </div>{lede_after_html}"""

    elif layout == "figure2":
        stats_html = "".join(stat_html(s, code_names) for s in stats)
        # lede2 is rendered with line breaks preserved (br) so structured
        # lists — e.g. enumerations of compiler stages — read clearly.
        lede2 = br(slide.get("lede2", ""), code_names)
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

    elif layout == "demo":
        # Centered hero layout — for the /demo/ video page.
        # `figure` carries the <video> element; `figure_poster` (optional) is the poster image.
        lede2_html = f'\n    <p class="lede lede-followup">\n      {lede2}\n    </p>' if lede2 else ""
        body = f"""<p class="eyebrow">{eyebrow}</p>
    <h2>
      {title}
    </h2>
    <div class="demo-frame">
      {figure}
    </div>
    <p class="lede lede-flush demo-lede">
      {lede}
    </p>{lede2_html}"""

    else:
        raise BuildError(f"Unknown layout: {layout}")

    return f"""<section class="slide" data-context="{context}">
  <div class="stage">
    {body}
  </div>
  <footer class="foot">
    <span>{foot}</span>
  </footer>
</section>"""


# ── Document assembly ──────────────────────────────────────────────────────

CHROME_START = "<!--HELMSMATE:CHROME:START-->"
CHROME_END = "<!--HELMSMATE:CHROME:END-->"
WEBFONTS_START = "<!--HELMSMATE:WEBFONTS:START-->"
WEBFONTS_END = "<!--HELMSMATE:WEBFONTS:END-->"

DEFAULT_SITE_WORD = (
    'troid<span class="amp">&amp;</span>robby'
    '<span class="slash">/</span><span class="suffix">v1</span>'
)
DEFAULT_SITE_HOME_URL = "https://robby.thecontrarian.in/"
DEFAULT_SITE_HOME_LABEL = "troid & robby — back to the gallery"
DEFAULT_CODE_NAMES = ("robby", "troid")
DEFAULT_MARK = "assets/sef-corona.svg"


@dataclass
class BuildResult:
    """Outcome of a build."""

    html: str
    slides: int
    theme: str
    warnings: list[str] = field(default_factory=list)
    outline: list[dict[str, Any]] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.html.encode("utf-8"))


def _strip_block(text: str, start: str, end: str) -> str:
    """Remove a marked block, including the markers."""
    out: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if start in line:
            skipping = True
            continue
        if skipping:
            if end in line:
                skipping = False
            continue
        out.append(line)
    return "".join(out)


def _strip_markers(text: str) -> str:
    for marker in (CHROME_START, CHROME_END, WEBFONTS_START, WEBFONTS_END):
        text = text.replace(marker + "\n", "").replace(marker, "")
    return text


def _figure_asset_markup(slide: dict, asset_roots: tuple[Path, ...]) -> str:
    """Inline a slide's ``figure_asset`` — keeps deck payloads small."""
    rel = slide.get("figure_asset")
    if not rel:
        return ""
    path = paths.resolve_asset(str(rel), *asset_roots)
    if path is None:
        raise BuildError(f"figure_asset not found: {rel}")
    return asset_to_markup(path)


def site_chrome_warning(deck: dict) -> str | None:
    """Warn when a deck carries the HelmsMate site chrome.

    The chrome carries the logo, the theme toggle and links to
    robby.thecontrarian.in. That is right for the project's own deck and
    wrong for a deck authored elsewhere, so callers that serve decks to
    outside clients surface this.
    """
    chrome = (deck.get("deck", {}) or {}).get("chrome", True)
    if chrome is False or isinstance(chrome, dict):
        return None
    return (
        "The deck includes the HelmsMate site chrome (logo, theme toggle and links to "
        "robby.thecontrarian.in). Set 'deck.chrome: false' for a standalone deck, or a "
        "mapping ('word', 'home_url', 'home_label') to brand it."
    )


def _asset_roots(asset_roots: tuple[Path, ...] | None) -> tuple[Path, ...]:
    """Search path for assets: the caller's roots first, the repo's built-ins last.

    The built-ins (the brand mark, the chrome icons) are always reachable, so
    a caller adding a workspace does not have to re-declare the repository.
    """
    roots: list[Path] = [Path(r) for r in (asset_roots or ())]
    repo = paths.repo_root()
    if repo not in roots:
        roots.append(repo)
    return tuple(roots)


def build_html(
    deck: dict,
    *,
    theme: dict | None = None,
    theme_name: str | None = None,
    template: str | None = None,
    asset_roots: tuple[Path, ...] = (),
    themes_dir: Path | None = None,
) -> BuildResult:
    """Render a deck dict into a self-contained HTML document.

    ``asset_roots`` is where ``brand.mark`` and ``figure_asset`` are looked
    up — the repo root by default, plus a workspace when the API serves decks.
    """
    if not isinstance(deck, dict):
        raise BuildError("Deck must be a mapping.")

    deck_cfg = deck.get("deck", {}) or {}
    brand = deck_cfg.get("brand", {}) or {}

    theme_name = theme_name or deck.get("theme") or themes.DEFAULT_THEME
    if theme is None:
        try:
            theme = themes.load_theme(theme_name, themes_dir)
        except FileNotFoundError as exc:
            raise BuildError(str(exc)) from exc

    roots = _asset_roots(asset_roots)

    chrome = deck_cfg.get("chrome", True)
    chrome_cfg = chrome if isinstance(chrome, dict) else {}

    # Brand mark → frozen header + favicon. Optional: a deck with no mark
    # falls back to the built-in one rather than failing to build.
    mark_rel = brand.get("mark", "")
    if mark_rel:
        logo_path = paths.resolve_asset(str(mark_rel), *roots)
        if logo_path is None:
            raise BuildError(f"brand.mark not found: {mark_rel}")
    else:
        fallback = paths.resolve_asset(DEFAULT_MARK, *roots)
        if fallback is None:
            raise BuildError(f"brand.mark not found and no default mark is available: {DEFAULT_MARK}")
        logo_path = fallback
    logo_svg = read_svg(logo_path)
    favicon = svg_to_data_uri(logo_svg)

    # Site chrome icons — match the React app's chrome so deck/demo feel
    # identical. Inlined so the static pages don't depend on /icons/*.
    # Not needed when the chrome is stripped, so do not look for them.
    if chrome is False:
        thin_glasses = ""
        regular_glasses = ""
    else:
        icons: dict[str, str] = {}
        for key, rel in (
            ("thin", "assets/icons/thin-sunglasses.svg"),
            ("regular", "assets/icons/regular-sunglasses.svg"),
        ):
            icon_path = paths.resolve_asset(rel, *roots)
            if icon_path is None:
                raise BuildError(f"Chrome icon not found: {rel}")
            icons[key] = read_svg(icon_path)
        thin_glasses = icons["thin"]
        regular_glasses = icons["regular"]

    code_names = brand.get("code_names", list(DEFAULT_CODE_NAMES))

    if template is None:
        template_path = paths.template_file()
        if not template_path.exists():
            raise BuildError(f"Template not found: {template_path}")
        template = template_path.read_text(encoding="utf-8")

    slides = deck.get("slides", []) or []
    total = len(slides)
    foot_default = (deck_cfg.get("footer", {}) or {}).get("default", "")

    slides_html = "\n\n".join(
        slide_html(
            slide,
            i + 1,
            total,
            foot_default,
            code_names=code_names,
            figure_asset_html=_figure_asset_markup(slide, roots),
        )
        for i, slide in enumerate(slides)
    )

    if chrome is False:
        template = _strip_block(template, CHROME_START, CHROME_END)
    webfonts = deck_cfg.get("webfonts", True)
    if not webfonts:
        template = _strip_block(template, WEBFONTS_START, WEBFONTS_END)

    # A supplied wordmark is text, exactly like brand.word: escaped, with
    # inline markup honoured. The default carries markup and is used as-is.
    user_word = chrome_cfg.get("word")
    site_word = bold(user_word, code_names) if user_word else DEFAULT_SITE_WORD
    site_home_url = chrome_cfg.get("home_url") or DEFAULT_SITE_HOME_URL
    site_home_label = chrome_cfg.get("home_label") or DEFAULT_SITE_HOME_LABEL

    output = template
    output = output.replace("{{DECK_TITLE}}", esc(deck_cfg.get("title", "HelmsMate")))
    output = output.replace("{{FAVICON}}", favicon)
    output = output.replace("/*{{THEME_VARS}}*/", themes.css_vars_from_theme(theme))
    output = output.replace("{{LOGO_SVG}}", logo_svg)
    output = output.replace("{{BRAND_WORD}}", bold(brand.get("word", ""), code_names))
    output = output.replace("{{BRAND_ALT}}", attr(brand.get("alt", "Brand mark")))
    output = output.replace("{{SITE_WORD}}", site_word)
    output = output.replace("{{SITE_HOME_URL}}", attr(site_home_url))
    output = output.replace("{{SITE_HOME_LABEL}}", attr(site_home_label))
    output = output.replace("{{ICON_THIN_GLASSES}}", thin_glasses)
    output = output.replace("{{ICON_REGULAR_GLASSES}}", regular_glasses)
    output = output.replace("{{SLIDE_COUNT}}", str(total))
    output = output.replace("{{SLIDES}}", slides_html)
    output = _strip_markers(output)

    warnings: list[str] = []
    outline: list[dict[str, Any]] = []
    for i, slide in enumerate(slides, 1):
        outline.append(
            {
                "index": i,
                "layout": slide.get("layout", "opener"),
                "context": slide.get("context", ""),
                "title": " ".join(str(slide.get("title", "")).split()),
            }
        )
        if not slide.get("context"):
            warnings.append(f"slides[{i - 1}]: no 'context' — the slide index menu will show a generic label.")
        if slide.get("layout") in ("cards2", "cards3"):
            want = 2 if slide["layout"] == "cards2" else 3
            got = len(slide.get("cards", []) or [])
            if got < want:
                warnings.append(
                    f"slides[{i - 1}]: {slide['layout']} shows {got} card(s); {want} is the intended shape."
                )

    return BuildResult(
        html=output,
        slides=total,
        theme=theme_name,
        warnings=warnings,
        outline=outline,
        assets=[str(p) for p in roots],
    )
