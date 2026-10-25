# helmsmate — technical specification

The mechanics behind HelmsMate, for contributors and the curious. The README
covers what it does and how to get it; this file covers how it works.

HelmsMate is a self-contained project. It carries no dependency on, and no
link to, any other site or project: the theme, the chrome, the assets and the
example decks are its own.

## Design rules

- **Everything editorial lives in `deck.yaml`; everything structural lives in
  the engine.** A deck file carries content only. Layout, theming, navigation
  and the layout invariants are the engine's business.
- **The catalog is the code.** `helmsmate/spec.py` holds one table of layouts
  and fields. The renderer draws from it, the validator checks against it, and
  the API and MCP layers publish it as JSON Schema. A layout cannot change in
  one place and stay stale in another.
- **One file out.** The built deck is a single `index.html` with inline CSS,
  JS and SVG. It opens from `file://` with nothing missing. The one exception
  is opt-in: a theme that names webfonts links Google Fonts, and
  `deck.webfonts: false` strips even that.
- **The engine never guesses.** A title breaks where the author said it breaks
  (`|` in YAML, or a newline). Layout is named, never inferred from field
  counts.
- **Errors carry a path and a hint.** Every validation failure addresses one
  field by index — `slides[3].cards[1].h` — and says what to do about it.
- **The library is the product.** The REST API and the MCP server are thin
  wrappers over the same functions, so the three surfaces cannot drift.

## Engine invariants

These are the bugs and constraints discovered while building the Saint Elms
Fire deck. The engine's `template.html` **must** preserve them.

1. **Viewport/track split.** `.deck` owns `overflow:hidden`; `.track` owns the
   `translateX` transform. Never both on one element — the overflow clip is
   applied in local space and moves with the transform, blanking every slide
   after the first.
2. **Panes need explicit width.** `.slide { width: 100vw }`, not `min-width`. A
   flex item with `flex-shrink:0` and no width resolves its base size to
   *max-content*, and slides silently grow wider than the viewport on narrow
   screens.
3. **Frozen header.** Brand + rule live in a `.deck-head` overlay outside the
   track; the right-side context label is swapped from each slide's `context:`
   field. Slide `padding-top` = header block height exactly (120px desktop /
   96px mobile).
4. **Card rows equal-height** come free from grid stretch — don't add fixed
   heights.
5. **Scroll triggers.** The slide scrolls when it is narrow
   (`max-width:900px` — single-column grids, so footers stay reachable) or
   short (`max-height:620px` — a shallow window, where even a desktop grid
   runs out of room). Below 900px the header shrinks and holds position.
6. **Page counter centered** between ‹ › with tabular-nums min-width; dots
   bottom-left; progress bar bottom edge; hash routing (`#/N`) with
   back/forward support.
7. **Zero CDN.** Logos are inlined SVG; favicon is a data-URI. The output file
   must open from `file://` with nothing missing.
8. **The chrome is optional and neutral.** The site bar carries the logo, a
   theme toggle and a link to the source repository. It is HelmsMate's own
   chrome, not another site's — `deck.chrome: false` removes it, and a
   mapping (`word`, `home_url`, `home_label`) rebrands it.

## The content model

The YAML has two levels: a `deck` block common to every slide, and a `slides`
list of pure data.

```yaml
deck:                      # ── common to every slide ──
  title: Saint Elms Fire — Intent · Vision · The Learner First   # <title> + tab
  brand:
    mark: assets/helm.svg          # inlined at build; or literal `svg:` block
    word: Saint **Elms** Fire      # **bold** segment supported
    link_reset: true               # clicking the mark returns to slide 1
  footer:                          # left-aligned tagline default; per-slide override allowed
    default: Guidance through the storm
  nav:
    style: pill                    # ‹ N / 8 › with counter centered between buttons
    dots: true
    progress: true

theme: mariners-chart      # named theme; themes/*.theme.yaml hold palette + fonts

slides:                    # ── per-slide content, pure data ──
  - layout: opener
    context: Intent · Purpose · Vision     # label in the frozen header (right side)
    eyebrow: An AI-native LMS
    title: |
      Guidance through
      the storm.
    lede: Most learning platforms are digital filing cabinets…
    stats:
      - { big: "3", small: "Focus areas: Friend, Philosopher, Guide" }
      - { big: Day 1, small: "Your second brain starts building" }
    foot: St. Elmo's fire · the blue-white corona at the masthead

  - layout: cards2            # two equal-height cards
    context: Why we built it
    title: Most LMSs are designed for Management.|Learning deserves its own architect.
    cards:
      - { k: The incumbent, h: Designed for administrators, p: Proctored rows… }
      - { k: The correction, h: Designed for the learner, p: Elms inverts… }
    note:                      # optional mono block under the cards
      - Every learner is different.
      - Temperament, pace, modality, prior knowledge — the system starts there.
```

### Layout registry

| layout      | shape                                        | seen on Elms slide |
|-------------|----------------------------------------------|--------------------|
| `opener`    | eyebrow · giant title · lede · stats row     | 1                  |
| `cards2`    | title · 2 equal-height cards · optional note | 2, 7               |
| `cards3`    | title · 3 equal-height cards · optional lede | 3, 5, 6            |
| `figure2`   | title · figure (inline SVG) left, text right | 4                  |
| `closer`    | eyebrow · title · two ledes                  | 8                  |
| `demo`      | title · centred media frame (video)          | — (demo page)      |

Titles take an explicit break with `|` (or YAML `\n`) — the engine never
guesses.

### Field conventions

| Field | Kind | Notes |
| --- | --- | --- |
| `title` | richtext | newlines fold into balanced line breaks; `\|` forces a break |
| `lede`, `lede_after` | richtext | newlines fold into natural prose |
| `lede2`, `note` | lines | newlines are preserved as line breaks |
| `cards[]` | cards | `{k, h, p}` — `h` required, `k` and `p` optional |
| `stats[]` | stats | `{big, small}` — a figure and its caption; max 4 |
| `figure` | html | raw HTML, passed through untouched |
| `figure_asset` | asset | path to an SVG/raster, inlined at build |
| `grid_mt` | int | margin-top override for the card/figure grid |
| `context` | text | label in the frozen header |
| `foot` | text | footer line; falls back to `deck.footer.default` |

`figure` is raw HTML by design — trusted content only. Everything else is
escaped.

### Themes

A theme lives in `themes/<name>.theme.yaml` and flattens into CSS custom
properties: `colors.beacon.500` becomes `--beacon-500`, `fonts.display`
becomes `--font-display`.

| Theme | Look | Modes |
| --- | --- | --- |
| `mariners-chart` | beacon blues, marine ink, serif/sans/mono | light |
| `archive-trace` | archive paper, charcoal, vermilion | light + dark |

## Repo layout

```
helmsmate/
├── README.md                 # what it is, and how to use it
├── TECH-SPEC.md              # this file
├── docs/
│   ├── INSTALL.md            # the install prompt, and the manual install
│   └── api.md                # REST API reference
├── pyproject.toml            # package metadata + console scripts
├── deck.example.yaml         # annotated starter (the Elms deck, ported)
├── demo.yaml                 # the single-slide demo page
├── skills/
│   └── helmsmate-decks/
│       └── SKILL.md          # the companion skill the installer ships
├── themes/
│   ├── mariners-chart.theme.yaml
│   └── archive-trace.theme.yaml
├── engine/
│   ├── template.html         # CSS + shell + nav JS with invariant guards
│   └── build.py              # legacy CLI entry point — a shim over the package
├── helmsmate/                # the library
│   ├── spec.py               # THE contract: layouts, fields, JSON Schema, catalog
│   ├── engine.py             # deck dict → self-contained HTML
│   ├── validate.py           # friendly, path-addressed errors
│   ├── themes.py             # theme registry
│   ├── store.py              # built decks on disk, with identity
│   ├── api.py                # REST API (stdlib only)
│   ├── mcp.py                # MCP server (tools/list, tools/call)
│   ├── cli.py                # helmsmate build | serve | mcp | schema | …
│   └── paths.py              # where the template, themes and assets live
├── scripts/
│   ├── install.py            # installs HelmsMate for a coding agent
│   ├── shoot.py              # headless screenshots of every slide → shots/
│   ├── serve.py              # static dev server for dist/
│   ├── smoke.py              # end-to-end service check
│   └── verify.py             # DOM assertions: logo frozen, no h-overflow,
│                             #   equal card heights, footer in viewport, counter centered
├── tests/                    # stdlib unittest — no test framework needed
└── dist/                     # build output (gitignored except releases)
```

**Build tool:** Python 3 + PyYAML only. No other dependencies.
**Verification:** Playwright headless (dev dependency, not shipped).

## The library

```python
from helmsmate import build_html, validate_deck

result = build_html(deck_dict)          # -> .html, .slides, .warnings, .outline
problems = validate_deck(deck_dict)     # -> [ValidationIssue(path, message, hint)]
```

## The REST API

```bash
python -m helmsmate.api --port 8787
```

The server binds to `127.0.0.1` and sends no CORS header, so a page in your
browser cannot read it by accident. To expose it, add a token (`--token`) and,
for browser clients, an origin (`--allow-origin`). A deck is content — `figure`
is raw HTML by design — so treat the API as trusted-input-only. See
[docs/api.md](docs/api.md#trust-boundary).

| method | path                        | what it does                                    |
|--------|-----------------------------|-------------------------------------------------|
| GET    | `/`                         | endpoint index                                   |
| GET    | `/openapi.json`             | OpenAPI 3.1 description                          |
| GET    | `/api/schema`               | the deck contract: JSON Schema, layouts, notes   |
| GET    | `/api/layouts`              | layout catalog                                   |
| GET    | `/api/layouts/{name}`       | one layout, with its strict schema               |
| GET    | `/api/themes`               | available themes                                  |
| POST   | `/api/decks`                | build and store a deck                           |
| POST   | `/api/decks/validate`       | check a deck without building it                 |
| GET    | `/api/decks`                | list stored decks                                |
| GET    | `/api/decks/{id}`           | metadata + authored source                       |
| GET    | `/api/decks/{id}/yaml`      | the authored source                              |
| GET    | `/api/decks/{id}/html`      | the built presentation                           |
| GET    | `/decks/{id}/`              | the built presentation, in a browser             |
| DELETE | `/api/decks/{id}`           | remove a stored deck                             |
| POST   | `/mcp`                      | MCP tool calling over JSON-RPC                   |

```bash
curl -s localhost:8787/api/decks -H 'content-type: application/json' -d '{
  "deck": {
    "deck": {"title": "Quarterly review", "brand": {"mark": "assets/sef-corona.svg"}},
    "theme": "mariners-chart",
    "slides": [
      {"layout": "opener", "context": "Opening", "title": "Q3 in one page.",
       "lede": "Three numbers that matter.", "stats": [{"big": "42%", "small": "growth"}]},
      {"layout": "cards2", "context": "Why", "title": "What moved.",
       "cards": [{"k": "Up", "h": "Retention", "p": "…"}, {"k": "Down", "h": "Churn", "p": "…"}]}
    ]
  }
}'
```

An invalid deck comes back `422` with a path and a hint for every problem:

```json
{"error": {"code": "invalid_deck", "message": "The deck has 1 validation error(s)...",
  "details": [{"path": "slides[0].layout", "message": "Unknown layout 'opener2'.",
               "hint": "One of: opener, cards2, cards3, figure2, closer, demo.",
               "severity": "error"}]}}
```

Full reference: [`docs/api.md`](docs/api.md).

## The MCP server

MCP is how an LLM *discovers* the functions: it lists the tools, reads their
input schemas, and calls them. The tools are the same library functions.

| tool              | what it gives the LLM                                  |
|-------------------|---------------------------------------------------------|
| `list_themes`     | themes available for the deck                           |
| `list_layouts`    | what each layout shows and takes, with examples         |
| `get_deck_schema` | the full contract: JSON Schema, catalog, conventions    |
| `validate_deck`   | per-field errors with paths and hints                    |
| `build_deck`      | the finished presentation: id, URL, outline, warnings   |
| `list_decks`      | decks already in the workspace                          |
| `read_deck`       | the authored source of a stored deck                    |

The transport is JSON-RPC 2.0. `helmsmate/mcp.py` speaks the MCP stdio
transport (newline-delimited JSON) for local clients; the REST API mounts the
same handler at `POST /mcp` for remote ones.

The loop an LLM runs is short and self-correcting:

1. `get_deck_schema` → learns the layouts and their fields.
2. `build_deck` with an authored deck.
3. If it fails, each error names a path (`slides[3].cards[1].h`) and a hint;
   fix and retry.

### Registering with a coding agent

Point the agent at the stdio server and the seven tools show up in its tool
list. `PYTHONPATH` points at the checkout, because the server is launched from
whatever directory the client happens to be in and `helmsmate` is not
installed system-wide:

```json
{
  "mcpServers": {
    "helmsmate": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "helmsmate.mcp"],
      "env": {
        "PYTHONPATH": "/path/to/helmsmate",
        "HELMSMATE_WORKSPACE": "/path/to/helmsmate/decks"
      }
    }
  }
}
```

| Client | Config |
| --- | --- |
| MiniMax Code | `~/.minimax/mcp.json` (extra keys: `type`, `enabled`, `configured`, `builtin`, `description`) |
| Claude Code | `~/.claude.json` (user) or `.mcp.json` (project) |
| Cursor | `~/.cursor/mcp.json` (user) or `.cursor/mcp.json` (project) |

A companion skill makes the agent reach for HelmsMate unprompted. It ships
with the repository at `skills/helmsmate-decks/SKILL.md` and is installed into
the agent's skills directory:

| Client | Skills directory |
| --- | --- |
| Any (canonical) | `~/.agents/skills/helmsmate-decks/` |
| MiniMax Code | `~/.minimax/skills/helmsmate-decks/` |
| Claude Code | `~/.claude/skills/helmsmate-decks/` |
| Cursor | `~/.cursor/skills/helmsmate-decks/` |

## The installer

`scripts/install.py` does the four install steps and proves each one.

```bash
python3 scripts/install.py                     # detect the client
python3 scripts/install.py --client claude     # be explicit
python3 scripts/install.py --client all        # register everywhere
python3 scripts/install.py --repo /path/to/checkout --skip-verify
```

| Flag | Meaning |
| --- | --- |
| `--client` | `auto` \| `minimax` \| `claude` \| `cursor` \| `all` |
| `--dir` | checkout location (default `~/tools/helmsmate`) |
| `--repo` | use an existing checkout instead of cloning |
| `--workspace` | where built decks are stored (default `<checkout>/decks`) |
| `--python` | interpreter for the MCP server (default `<checkout>/.venv/bin/python`) |
| `--skip-verify` | do not run the MCP round trip |

The steps, in order:

1. **Checkout** — clone `https://github.com/thecont1/helmsmate.git`, or use
   `--repo`.
2. **Interpreter** — create `<checkout>/.venv` and install PyYAML into it.
3. **Registration** — write the server entry into the client's config. Every
   write is an overwrite, so re-running is safe.
4. **Skill** — copy `skills/helmsmate-decks/SKILL.md` into the skills
   directories for the detected clients, and link it for MiniMax Code.

Then it **verifies**: it spawns the server, performs the MCP `initialize` and
`tools/list` handshake, asserts all seven tools came back, and builds a
two-slide deck through `build_deck`. The deck file on disk is the proof. A
non-zero exit means something failed — the report says which step.

The script is stdlib-only, and writes to exactly three places: the checkout,
the client's MCP config, and the skills directories it names.

`docs/INSTALL.md` carries the same procedure as a paste-into-your-agent
prompt, and as manual steps for people who would rather do it themselves.

## The CLI

```bash
python -m helmsmate.cli build deck.yaml --out dist/index.html
python -m helmsmate.cli validate deck.yaml
python -m helmsmate.cli serve --port 8787
python -m helmsmate.cli schema            # the contract, as JSON
python -m helmsmate.cli layouts           # the layout catalog
python -m helmsmate.cli themes            # available themes
python -m helmsmate.cli decks             # decks in the workspace
```

`python engine/build.py deck.yaml` still works — it is a shim over the package.

## How a deck is stored

Built decks live in the **workspace** (`<checkout>/decks` by default,
`HELMSMATE_WORKSPACE` to move it):

```
decks/<deck-id>/
    deck.yaml     # the authored source — this is what an edit would touch
    index.html    # the built presentation
    meta.json     # title, slide count, timestamps, theme
```

The deck id is a slug of the title plus a hash of the deck's content, so
building the same deck twice updates one deck while two different decks with
the same title get their own ids.

Keeping the source next to the build is what makes editing possible: an edit
applies to `deck.yaml` and rebuilds, rather than trying to patch generated
HTML.

## Verification

```bash
python scripts/smoke.py                       # does the service actually work?
python -m unittest discover -s tests -t .      # the unit and integration suite
python scripts/shoot.py <deck-dir>             # screenshots of every slide
python scripts/verify.py <deck-dir>            # DOM assertions
```

`scripts/smoke.py` is the quick one: it starts the REST API on an ephemeral
port, drives it the way an LLM would (discovery, build, read back), runs the
same loop over MCP, and — if Playwright is installed — opens the built deck in
a browser and checks that it renders. It prints a checklist and exits non-zero
if anything fails.

`scripts/shoot.py` and `scripts/verify.py` need Playwright:

```bash
python3 -m venv .venv && .venv/bin/pip install playwright && .venv/bin/playwright install chromium
```

`verify.py` asserts the things that are easy to break: the header stays
frozen, nothing overflows horizontally, card rows are equal height, the footer
is inside the viewport, and the page counter is centered between the arrows.

The unit suite is stdlib-only and covers the contract, the validator's error
paths, the renderer (including that a list `note:` renders as lines and never
as a Python repr), the store, the REST API over a real socket, the MCP
JSON-RPC surface, and the transport edges a bad client can reach.

## Migration path from the Elms deck

1. Port `saint-elms-fire/deck/index.html` → `deck.yaml`
   (pure mechanical translation; the 8 slides map onto the 5 layouts above).
2. Extract the Mariner's Chart palette/fonts from the inline `:root` → theme YAML.
3. Generalize `template.html` from the fixed file (layouts as Jinja-free string
   templates — keep it readable).
4. Port the checks we ran by hand (elementsFromPoint paint test, footer/overflow
   measurements, counter centering) into `scripts/verify.py` as CI-able assertions.
5. Point the Elms deck at HelmsMate: its folder keeps only `deck.yaml` + built output.

## Roadmap

- **v0** — the engine: one theme, five layouts, the Elms deck as the example.
- **v1** — schema validation with friendly errors; `helmsmate new`; watch mode.
- **v2** — fragments (animated build lists), presenter notes via query param,
  PDF export through print CSS, second theme (paper/ink light & reef dark).
- **v3 — the service layer (done).** The engine became a library with a
  machine-readable contract, exposed over REST and MCP. An LLM can now discover
  the layouts, author a deck and get a finished presentation back.
- **v3.1 — the installer (done).** One prompt gets HelmsMate into a coding
  agent: checkout, dependencies, MCP registration, companion skill, and a
  verified build.
- **v4 — editing (next).** The same contract, pointed the other way: read a
  stored deck, apply an edit, rebuild. The seams are in place — `read_deck`
  returns the authored source, `store.save` writes it back, and the validator
  already reports on a deck before it is built. The shape it should take:
  slide-level operations (add, replace, remove, reorder) rather than a free-form
  text patch, so an edit is auditable and reversible.
