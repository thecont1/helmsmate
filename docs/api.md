# HelmsMate API reference

Two transports, one set of functions:

- **REST** — for other software. Standard library HTTP, JSON in and out.
- **MCP** — for LLMs. The same functions as tools, discoverable via `tools/list`.

Both run on the same process:

```bash
python -m helmsmate.api --port 8787        # REST + POST /mcp
python -m helmsmate.mcp                    # stdio MCP, for a local client
```

---

## Discovery

### `GET /`

The endpoint index. A cheap way for a client to find its way around.

```json
{
  "service": "HelmsMate API",
  "version": "0.1.0",
  "discovery": {
    "openapi": "/openapi.json",
    "deck_schema": "/api/schema",
    "layouts": "/api/layouts",
    "themes": "/api/themes"
  },
  "decks": { "build": "POST /api/decks", "validate": "POST /api/decks/validate", "…": "…" },
  "llm": { "mcp": "POST /mcp (JSON-RPC 2.0)", "tools": ["list_themes", "…"] }
}
```

### `GET /openapi.json`

OpenAPI 3.1. Every endpoint, with request bodies and the deck schema inline.

### `GET /api/schema`

The contract. **This is what an LLM reads before writing a deck.**

```json
{
  "schema_version": "1.0",
  "deck_schema": { "$schema": "https://json-schema.org/draft/2020-12/schema", "…": "…" },
  "layouts": [
    {
      "layout": "opener",
      "summary": "Opening slide. Eyebrow, a large title, a lead paragraph and a row of figures.",
      "required_fields": ["title"],
      "fields": {
        "eyebrow": { "kind": "text", "description": "Small label above the title…" },
        "stats":  { "kind": "stats", "max_items": 4, "description": "Row of figure + caption pairs." }
      },
      "example_yaml": "- layout: opener\n  title: …"
    }
  ],
  "authoring_notes": ["Deck-level keys: `deck`, `theme`, `slides`.", "…"],
  "conventions": { "text_kinds": { "text": "one line, newlines fold", "…": "…" } }
}
```

### `GET /api/layouts` · `GET /api/layouts/{name}`

The layout catalog, and one layout's strict JSON Schema (the `required` list
reflects that layout, unlike the flat schema used for tool inputs).

### `GET /api/themes`

```json
{
  "themes": [
    {
      "name": "mariners-chart",
      "label": "Mariner's Chart",
      "modes": ["light"],
      "palette": { "paper": "#FBFBFD", "chart": "#F5F7FB", "beacon-500": "#4A68C8" },
      "fonts": { "display": "…", "sans": "…", "mono": "…" }
    }
  ],
  "default": "mariners-chart"
}
```

---

## Decks

### `POST /api/decks`

Build a deck and store it.

**Body** — JSON or YAML. Three shapes are accepted:

```jsonc
{ "deck": { "deck": {…}, "theme": "…", "slides": [ … ] }, "deck_id": "optional" }
{ "deck": { … }, "theme": "…", "slides": [ … ] }        // a bare deck
// …or the YAML text of a deck, with content-type: text/yaml
```

`deck_id` is optional; it defaults to a slug of the title plus a short hash.

**201 Created**

```json
{
  "deck_id": "quarterly-review-7f3a2b",
  "title": "Quarterly review",
  "slides": 2,
  "theme": "mariners-chart",
  "bytes": 43431,
  "url": "http://127.0.0.1:8787/decks/quarterly-review-7f3a2b/",
  "html_path": "/path/to/decks/quarterly-review-7f3a2b/index.html",
  "source_path": "/path/to/decks/quarterly-review-7f3a2b/deck.yaml",
  "outline": [
    { "index": 1, "layout": "opener", "context": "Opening", "title": "Q3 in one page." }
  ],
  "warnings": [],
  "build_warnings": ["The deck includes the HelmsMate site chrome…"]
}
```

**422 Unprocessable Content** — the deck has validation errors.

```json
{
  "error": {
    "code": "invalid_deck",
    "message": "The deck has 2 validation error(s). Each error has a path and a hint.",
    "details": [
      { "path": "slides[0].layout", "message": "Unknown layout 'opener2'.",
        "hint": "One of: opener, cards2, cards3, figure2, closer, demo.", "severity": "error" },
      { "path": "slides[1].cards[0].h", "message": "Card heading 'h' is required.",
        "hint": "", "severity": "error" }
    ]
  }
}
```

### `POST /api/decks/validate`

Same body, no side effects. Always `200`:

```json
{ "ok": false, "errors": [ … ], "warnings": [ … ], "message": "1 error(s) to fix." }
```

### `GET /api/decks` · `GET /api/decks/{id}`

The list (newest first) and one deck — metadata plus the authored source as data.

### `GET /api/decks/{id}/yaml` · `GET /api/decks/{id}/html`

The authored source as YAML; the built presentation as HTML.

### `GET /decks/{id}/`

The built presentation, served for a browser. The deck's own JavaScript handles
slide routing, so `/decks/{id}/3` opens the third slide.

### `DELETE /api/decks/{id}`

Removes the stored deck. `404` if it is not there.

---

## Errors

Every error has the same shape:

```json
{ "error": { "code": "invalid_deck", "message": "…", "details": [ … ] } }
```

| status | code                | when                                          |
|--------|---------------------|-----------------------------------------------|
| 400    | `invalid_json`      | the body is not valid JSON                     |
| 400    | `invalid_yaml`      | the body is YAML but does not parse            |
| 400    | `invalid_deck`      | the body is not a deck                         |
| 400    | `build_failed`      | the deck is valid but cannot be rendered       |
| 400    | `invalid_deck_id`   | a deck id was rejected (build or delete)       |
| 400    | `bad_request`       | a malformed Content-Length header              |
| 401    | `unauthorized`      | a token is required and missing or wrong       |
| 404    | `not_found`         | no such route or deck                          |
| 404    | `unknown_layout`    | no such layout                                 |
| 405    | `method_not_allowed`| the path exists, the verb does not             |
| 411    | `length_required`   | a chunked body; send Content-Length            |
| 413    | `body_too_large`    | over 32 MB                                    |
| 422    | `invalid_deck`      | the deck has validation errors                 |
| 500    | `internal_error`    | an unexpected failure                          |

Validation paths are precise: `slides[3].cards[1].h` is the heading of the
second card on the fourth slide.

---

## Authentication

Off by default — the server binds to `127.0.0.1`. To expose it:

```bash
python -m helmsmate.api --host 0.0.0.0 --port 8787 --token "$HELMSMATE_TOKEN"
```

Then send either header:

```
Authorization: Bearer <token>
X-Helmsmate-Token: <token>
```

## CORS

Off by default, deliberately. A local service that answers
`Access-Control-Allow-Origin: *` can be read by any page open in the user's
browser, so a stray tab could read the decks on the machine. Browser clients
ask for it explicitly:

```bash
python -m helmsmate.api --allow-origin https://your.client
```

## Trust boundary

A deck is content, and the built presentation is that content rendered as
HTML. Two fields are raw HTML by design:

- `figure` — inline SVG or HTML, passed through untouched.
- `deck.chrome.word` — the site-bar wordmark, when given a custom value.

Everything else is escaped: `brand.word`, titles, ledes, cards, notes and the
chrome's `home_url` / `home_label` all go through the same escaping as the
rest of the text.

The consequence is the one every static site generator has: **a deck can
carry script, and the built file is served from the API's origin.** Anyone who
can POST a deck can therefore store script that runs on that origin.

The server limits the blast radius rather than pretending the problem is not
there. A deck is served with:

- `Content-Security-Policy: default-src 'self' data: blob:; … connect-src
  'none'; frame-src 'none'; form-action 'none'` — the deck renders and
  navigates, but it cannot open a network connection, so script inside a deck
  has no channel to fetch or post to the API or anywhere else;
- `X-Content-Type-Options: nosniff` — on every response.

That policy removes the deck's outbound network access. It is not a complete
boundary — the script still runs, and navigation is not a network request —
so a stored deck is not safe to view on an origin you care about. Treat the
API as trusted-input-only:

- bind it to `127.0.0.1` (the default), or put a token in front of it;
- don't view decks from untrusted authors on an origin that holds anything you
  care about;
- serve decks you did not author from a separate origin.

---

## MCP

`POST /mcp` speaks JSON-RPC 2.0, the same surface as the stdio transport.

```jsonc
// initialize
{"jsonrpc": "2.0", "id": 1, "method": "initialize",
 "params": {"protocolVersion": "2025-06-18", "capabilities": {}}}

// → {"jsonrpc":"2.0","id":1,"result":{
//      "protocolVersion":"2025-06-18",
//      "capabilities":{"tools":{"listChanged":false}},
//      "serverInfo":{"name":"helmsmate","version":"0.1.0"},
//      "instructions":"HelmsMate compiles a YAML deck into… "}}

// tools/list
{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}

// tools/call
{"jsonrpc": "2.0", "id": 3, "method": "tools/call",
 "params": {"name": "build_deck", "arguments": {"deck": { … }}}}
```

Supported protocol versions: `2025-06-18`, `2025-03-26`, `2024-11-05`. The
server answers with the version the client asked for when it knows it, and with
`2025-06-18` otherwise.

A tool result carries both a text block (the JSON payload, for models that read
text) and `structuredContent` (the same payload, for clients that read
structured output). A tool that fails sets `isError: true`.

| tool              | arguments              | returns                                        |
|-------------------|------------------------|------------------------------------------------|
| `list_themes`     | —                      | themes with palettes, fonts, colour modes       |
| `list_layouts`    | `layout?`              | the catalog, or one layout and its schema       |
| `get_deck_schema` | —                      | JSON Schema + catalog + authoring notes         |
| `validate_deck`   | `deck`                 | `{ok, errors[], warnings[]}`                    |
| `build_deck`      | `deck`, `deck_id?`     | `{deck_id, url, slides, outline, warnings}`     |
| `list_decks`      | —                      | stored decks                                   |
| `read_deck`       | `deck_id`              | the authored source + metadata                 |

`build_deck` validates before it renders. A deck with errors comes back with
`ok: false` and a list of errors, each with a path and a hint — the model
fixes them and calls again.

---

## Phase two: editing

The endpoints above go one way: deck in, presentation out. Editing goes the
other way and the pieces are already in place:

- `read_deck` returns the **authored source**, not the HTML.
- `store.save` writes source and build side by side.
- The validator already reports on a deck before it is built.

The shape it should take is slide-level operations rather than a free-form
patch, so an edit is auditable and can be reversed:

```jsonc
POST /api/decks/{id}/edit
{
  "operations": [
    { "op": "replace_slide", "index": 3, "slide": { "layout": "cards3", … } },
    { "op": "remove_slide", "index": 5 },
    { "op": "insert_slide", "index": 2, "slide": { … } },
    { "op": "set_theme", "theme": "archive-trace" }
  ]
}
```

Each operation returns the deck as it would be afterwards, so the caller can
confirm before it is applied. A `dry_run` flag runs the operations and returns
the result without writing.
