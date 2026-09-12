# HelmsMate

**Zero-dependency HTML slide decks, authored in YAML, compiled to a single self-contained `index.html`.**

Hived off from the Saint Elms Fire intro deck (`saint-elms-fire/deck/`), where the
engine proved itself on an 8-slide product narrative. HelmsMate is that engine, generalized:
you write one YAML file, run one build command, and get a beautiful presentation that runs
anywhere a browser exists — no CDN, no runtime fetch, no framework.

```
deck.yaml  ──▶  build  ──▶  index.html   (single file: HTML + CSS + JS + inline SVG logos)
                 │
                 └──▶  verify  ──▶  shots/slide-N.png  +  DOM assertion report
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
    eyebrow: The diagnosis
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

Titles take an explicit break with `|` (or YAML `\n`) — the engine never guesses.

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
   from `file://` with nothing missing.

## Repo layout (target)

```
helmsmate/
├── README.md                 # this file
├── deck.example.yaml         # annotated starter (the Elms deck, ported)
├── themes/
│   └── mariners-chart.theme.yaml   # beacon blues, marine ink, serif/sans/mono stacks
├── engine/
│   ├── template.html         # CSS + shell + nav JS with invariant guards (see above)
│   └── build.py              # deck.yaml + theme + template  →  index.html
├── scripts/
│   ├── shoot.py              # headless screenshots of every slide → shots/
│   └── verify.py             # DOM assertions: logo frozen, no h-overflow,
│                             #   equal card heights, footer in viewport, counter centered
└── dist/                     # build output (gitignored except releases)
```

**Build tool:** Python 3 + PyYAML only (install with `uv add pyyaml`). No other deps.
**Verification:** Playwright headless (dev dependency, not shipped).

## Migration path from the Elms deck

1. Port `saint-elms-fire/deck/index.html` → `deck.example.yaml`
   (pure mechanical translation; the 8 slides map onto the 5 layouts above).
2. Extract the Mariner's Chart palette/fonts from the inline `:root` → theme YAML.
3. Generalize `template.html` from the fixed file (layouts as Jinja-free string
   templates — keep it readable).
4. Port the checks we ran by hand (elementsFromPoint paint test, footer/overflow
   measurements, counter centering) into `scripts/verify.py` as CI-able assertions.
5. Point the Elms deck at HelmsMate: its folder keeps only `deck.yaml` + built output.

## Roadmap

- **v0** — the above, exactly. One theme, five layouts, Elms deck as the example.
- **v1** — schema validation with friendly errors; `helmsmate new`; watch mode.
- **v2** — fragments (animated build lists), presenter notes via query param,
  PDF export through print CSS, second theme (paper/ink light & reef dark).
