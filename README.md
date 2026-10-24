# HelmsMate

**Zero-dependency HTML slide decks, authored in YAML, compiled to a single self-contained `index.html`.**

Hived off from the Saint Elms Fire intro deck (`saint-elms-fire/deck/`), where the
engine proved itself on an 8-slide product narrative. HelmsMate is that engine, generalized:
you write one YAML file, run one build command, and get a beautiful presentation that runs
anywhere a browser exists — no CDN, no runtime fetch, no framework.

Now it also speaks to other software. The same functions are exposed as a
**REST API** and as **MCP tools**, so an LLM can discover the deck format,
author a deck, and get back a finished presentation — then edit it.

```
deck.yaml  ──▶  build  ──▶  index.html   (single file: HTML + CSS + JS + inline SVG logos)
                 │
                 ├──▶  verify  ──▶  shots/slide-N.png  +  DOM assertion report
                 │
                 └──▶  serve  ──▶  REST API + MCP tools  ──▶  other software, LLMs
```

## Content model (the core idea)

**Everything editorial lives in `deck.yaml`. Everything structural lives in the engine.**
The YAML has two levels:

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

### Layout registry (v0 — lifted 1:1 from the Elms deck)

| layout      | shape                                        | seen on Elms slide |
|-------------|----------------------------------------------|--------------------|
| `opener`    | eyebrow · giant title · lede · stats row     | 1                  |
| `cards2`    | title · 2 equal-height cards · optional note | 2, 7               |
| `cards3`    | title · 3 equal-height cards · optional lede | 3, 5, 6            |
| `figure2`   | title · figure (inline SVG) left, text right | 4                  |
| `closer`    | eyebrow · title · two ledes                  | 8                  |
| `demo`      | title · centred media frame (video)          | — (demo page)      |

Titles take an explicit break with `|` (or YAML `\n`) — the engine never guesses.

The catalog above is not documentation — it is the code. `helmsmate/spec.py` holds
one table of layouts and fields; the renderer draws from it, the validator checks
against it, and the API and MCP layers publish it as JSON Schema. A layout cannot
change in one place and stay stale in another.

## Engine invariants (bake these in; they were earned)

These are the bugs/constraints discovered while building the Elms deck. The engine's
`template.html` **must** preserve them:

1. **Viewport/track split.** `.deck` owns `overflow:hidden`; `.track` owns the
   `translateX` transform. Never both on one element — the overflow clip is applied in
   local space and moves with the transform, blanking every slide after the first.
2. **Panes need explicit width.** `.slide { width: 100vw }`, not `min-width`. A flex item
   with `flex-shrink:0` and no width resolves its base size to *max-content*, and slides
   silently grow wider than the viewport on narrow screens.
3. **Frozen header.** Brand + rule live in a `.deck-head` overlay outside the track;
   the right-side context label is swapped from each slide's `context:` field.
   Slide `padding-top` = header block height exactly (120px desktop / 96px mobile).
4. **Card rows equal-height** come free from grid stretch — don't add fixed heights.
5. **Mobile (<900px):** single-column grids + `.slide { overflow-y: auto }` so footers
   stay reachable; header shrinks and holds position.
6. **Page counter centered** between ‹ › with tabular-nums min-width; dots bottom-left;
   progress bar bottom edge; hash routing (`#/N`) with back/forward support.
7. **Zero CDN.** Logos are inlined SVG; favicon is a data-URI. The output file must open
   from `file://` with nothing missing. The one exception is opt-in: a theme that names
   webfonts (Source Serif, Space Grotesk, JetBrains Mono) links Google Fonts. Set
   `deck.webfonts: false` to strip those links for a fully offline deck.

## Repo layout

```
helmsmate/
├── README.md                 # this file
├── pyproject.toml            # package metadata + console scripts
├── deck.example.yaml         # annotated starter (the Elms deck, ported)
├── themes/
│   └── mariners-chart.theme.yaml   # beacon blues, marine ink, serif/sans/mono stacks
├── engine/
│   ├── template.html         # CSS + shell + nav JS with invariant guards (see above)
│   └── build.py              # legacy CLI entry point — now a shim over the package
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
│   ├── shoot.py              # headless screenshots of every slide → shots/
│   ├── serve.py              # static dev server for dist/
│   └── verify.py             # DOM assertions: logo frozen, no h-overflow,
│                             #   equal card heights, footer in viewport, counter centered
├── tests/                    # stdlib unittest — no test framework needed
└── dist/                     # build output (gitignored except releases)
```

**Build tool:** Python 3 + PyYAML only. No other dependencies.
**Verification:** Playwright headless (dev dependency, not shipped).

## Using it from other software

The library, the REST API and the MCP server are three doors into the same functions.

### Library

```python
from helmsmate import build_html, validate_deck

result = build_html(deck_dict)          # -> .html, .slides, .warnings, .outline
problems = validate_deck(deck_dict)     # -> [ValidationIssue(path, message, hint)]
```

### REST API

```bash
python -m helmsmate.api --port 8787
```

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

### MCP — for LLMs

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

Over stdio, for a local client:

```json
{
  "mcpServers": {
    "helmsmate": {
      "command": "python",
      "args": ["-m", "helmsmate.mcp"],
      "cwd": "/path/to/helmsmate"
    }
  }
}
```

Over HTTP, on the same server as the REST API: `POST /mcp`.

The loop an LLM runs is short and self-correcting:

1. `get_deck_schema` → learns the layouts and their fields.
2. `build_deck` with an authored deck.
3. If it fails, each error names a path (`slides[3].cards[1].h`) and a hint; fix and retry.

### CLI

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

Built decks live in the **workspace** (`./decks` by default, `HELMSMATE_WORKSPACE`
to move it):

```
decks/<deck-id>/
    deck.yaml     # the authored source — this is what an edit would touch
    index.html    # the built presentation
    meta.json     # title, slide count, timestamps, theme
```

Keeping the source next to the build is what makes the next phase possible:
an edit applies to `deck.yaml` and rebuilds, rather than trying to patch
generated HTML.

## Migration path from the Elms deck

1. Port `saint-elms-fire/deck/index.html` → `deck.yaml`
   (pure mechanical translation; the 8 slides map onto the 5 layouts above).
2. Extract the Mariner's Chart palette/fonts from the inline `:root` → theme YAML.
3. Generalize `template.html` from the fixed file (layouts as Jinja-free string
   templates — keep it readable).
4. Port the checks we ran by hand (elementsFromPoint paint test, footer/overflow
   measurements, counter centering) into `scripts/verify.py` as CI-able assertions.
5. Point the Elms deck at HelmsMate: its folder keeps only `deck.yaml` + built output.

## Tests

```bash
python -m unittest discover -s tests -t .
```

88 tests, stdlib only: the contract, the validator's error paths, the renderer
(including that a list `note:` renders as lines and never as a Python repr),
the store, the REST API over a real socket, and the MCP JSON-RPC surface.

## Roadmap

- **v0** — the engine: one theme, five layouts, the Elms deck as the example.
- **v1** — schema validation with friendly errors; `helmsmate new`; watch mode.
- **v2** — fragments (animated build lists), presenter notes via query param,
  PDF export through print CSS, second theme (paper/ink light & reef dark).
- **v3 — the service layer (done).** The engine became a library with a
  machine-readable contract, exposed over REST and MCP. An LLM can now discover
  the layouts, author a deck and get a finished presentation back.
- **v4 — editing (next).** The same contract, pointed the other way: read a
  stored deck, apply an edit, rebuild. The seams are in place — `read_deck`
  returns the authored source, `store.save` writes it back, and the validator
  already reports on a deck before it is built. The shape it should take:
  slide-level operations (add, replace, remove, reorder) rather than a free-form
  text patch, so an edit is auditable and reversible.
