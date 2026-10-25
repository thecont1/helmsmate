---
name: helmsmate-decks
description: Build presentations, slide decks, pitch decks, PPTX-style decks, conference talks or "slides for X" as self-contained HTML via the HelmsMate MCP server. Use whenever the user asks for a deck, slides, a presentation, a talk, or a visual summary — do not hand-write HTML slides.
---

# HelmsMate Decks

HelmsMate compiles a YAML deck into **one self-contained `index.html`** — HTML, CSS, JS and
inline SVG, no CDN, opens from `file://`. Use it instead of writing slides by hand.

The MCP server `helmsmate` is registered in the runtime. Its tools:

| tool | purpose |
|------|---------|
| `get_deck_schema` | the full contract: JSON Schema, layout catalog, authoring notes |
| `list_layouts` | what each layout shows and takes (optional: one layout) |
| `list_themes` | available themes with palettes and fonts |
| `validate_deck` | check a deck without building; errors carry `path` + `hint` |
| `build_deck` | build and store; returns deck id, HTML path, outline, warnings |
| `list_decks` / `read_deck` | decks already in the workspace; read authored source |

## Workflow

1. **`get_deck_schema`** once, before authoring. Do not guess the contract.
2. **Author the deck** as the object the schema describes:
   `{deck: {title, brand, footer, chrome, nav, webfonts}, theme: "<name>", slides: [...]}`.
   Each slide has `layout` plus only the fields that layout consumes.
3. **`build_deck`.** It validates first. On failure each error names a path
   (`slides[3].cards[1].h`) and a hint — fix the path and call again. Do not retry verbatim.
4. **Deliver** the built HTML. `html_path` is absolute; open it in the browser and hand the
   user the file.

Use `validate_deck` first when the deck is large (>8 slides) or you want a clean error
list before building.

## Layouts

`opener` (eyebrow · giant title · lede · stats row) · `cards2` / `cards3` (card grids,
optional `note:` block) · `figure2` (inline SVG or `figure_asset` left, text right) ·
`closer` (eyebrow · title · two ledes) · `demo` (centred media frame).

Titles take an explicit break with `|`. The engine never guesses — it folds newlines into
balanced breaks, so say where the line should break.

## Conventions

- **Titles break explicitly.** `title: "Most LMSs are built for management.|Learning deserves its own architect."`
- **Cards** are `{k: kicker, h: heading, p: body}`. `h` is required.
- **`stats`** are `{big: "42%", small: "growth"}` — a figure plus a caption.
- **`chrome`** adds the site bar (logo, theme toggle, a link to the source repository).
  It is on by default. For a standalone deck set `deck.chrome: false`; to brand it, pass
  `{word, home_url, home_label}`. `build_deck` warns when the default chrome is in.
- **Brand mark** — `deck.brand.mark` takes an SVG path resolved against the workspace
  `assets/` dir, then the repo's built-in assets. Otherwise the default mark is used.
- **`figure_asset`** is a path to an SVG/raster inlined into the media slot; prefer it over
  raw `figure` HTML for anything large. `figure` is raw HTML — trusted content only.
- **`webfonts: false`** strips the Google Fonts links for a fully offline deck.
- **Themes** are `mariners-chart` (default, light) and `archive-trace` (paper/vermilion,
  light + dark).

## Editing an existing deck

There is no edit tool — the loop is read → change → rebuild:

1. `read_deck` with the `deck_id` → the authored deck as structured data.
2. Mutate that object (add / replace / remove / reorder slides).
3. `build_deck` with the **same `deck_id`** → overwrites in place, source and HTML together.

The authored `deck.yaml` lives next to the built HTML, so a rebuild is the source of truth.

## Workspace

Decks are stored under the HelmsMate workspace (`HELMSMATE_WORKSPACE`, default
`<checkout>/decks`), one directory per deck:

```
<workspace>/<deck-id>/deck.yaml    # authored source
<workspace>/<deck-id>/index.html   # built presentation
<workspace>/<deck-id>/meta.json    # title, slide count, timestamps, theme
```

## Verify before shipping

From the checkout root:

```bash
python3 scripts/shoot.py <deck-dir>    # headless screenshots of every slide → shots/
python3 scripts/verify.py <deck-dir>   # DOM assertions: frozen header, no h-overflow,
                                        # equal card heights, footer in view, counter centred
python3 scripts/smoke.py               # end-to-end service check
```

`verify.py` and `shoot.py` need Playwright
(`pip install playwright && playwright install chromium`). Screenshots are also the fastest
way to show the user what they got.
