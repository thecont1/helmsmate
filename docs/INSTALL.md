# Installing HelmsMate

Two ways in. The short way is one prompt you paste into your coding agent and
forget about. The long way is here, if you'd rather do it by hand or need to
know what the agent is doing on your machine.

## The short way — paste this into your coding agent

Copy everything inside the block below and paste it into Claude Code, Cursor,
MiniMax Code, or any agent with a shell. It handles the clone, the
dependencies, the MCP registration, the companion skill, and the proof that it
all works.

```
Set up HelmsMate for me.

HelmsMate compiles one YAML deck into a single self-contained HTML
presentation, and exposes itself to you as MCP tools so you can build decks on
request.

Do the whole job without stopping to ask me questions, unless something
genuinely blocks you.

1. Get the code.
   git clone https://github.com/thecont1/helmsmate.git ~/tools/helmsmate
   Skip the clone if ~/tools/helmsmate already exists — use what is there.

2. Install and wire it up.
   cd ~/tools/helmsmate
   python3 -m venv .venv
   .venv/bin/pip install --upgrade pip
   .venv/bin/pip install PyYAML
   .venv/bin/python scripts/install.py --client <client> --python "$PWD/.venv/bin/python"

   <client> is the coding agent you are running inside: claude, cursor,
   minimax, or all. If you are not sure, run it with --client auto — it
   registers with every client it finds on this machine.

   If scripts/install.py is missing or fails, do the same four things by hand
   (they are written out in docs/INSTALL.md inside the repo):
     a. an interpreter with PyYAML,
     b. an MCP server entry in your client's config,
     c. the companion skill in your agent's skills directory,
     d. a verification build.

3. Restart or reload yourself so the new MCP server is picked up. Then confirm
   you can see seven tools: list_themes, list_layouts, get_deck_schema,
   validate_deck, build_deck, list_decks, read_deck.

4. Prove the loop end to end. Call get_deck_schema, author a two-slide deck
   against it, call build_deck, and open the index.html it returns.

5. Report back: where the checkout is, which client you registered, where
   decks will be written, and the path of the deck you just built.
```

## What the agent ends up with

- **A checkout** of HelmsMate, with a virtualenv holding its one dependency
  (PyYAML).
- **An MCP server** registered in your coding agent's config, so the seven
  tools appear in the agent's tool list.
- **A companion skill** in your agent's skills directory. This is the part that
  makes the agent reach for HelmsMate on its own when someone asks for a deck,
  instead of improvising HTML slides.
- **A verified deck** — the installer builds one over MCP and checks that the
  file landed on disk. If that step fails, nothing is reported as ready.

## Doing it by hand

### a. An interpreter with PyYAML

HelmsMate needs Python 3.10 or newer and nothing else.

```bash
cd ~/tools/helmsmate
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install PyYAML
```

A system interpreter with PyYAML already installed works just as well — point
the MCP entry at it and skip the virtualenv.

### b. The MCP server entry

Every client wants the same server, described the same way:

```json
{
  "helmsmate": {
    "command": "/absolute/path/to/helmsmate/.venv/bin/python",
    "args": ["-m", "helmsmate.mcp"],
    "env": {
      "PYTHONPATH": "/absolute/path/to/helmsmate",
      "HELMSMATE_WORKSPACE": "/absolute/path/to/helmsmate/decks"
    }
  }
}
```

Put it under the `mcpServers` key of whichever config your client reads:

| Client | User-level | Project-level |
| --- | --- | --- |
| MiniMax Code | `~/.minimax/mcp.json` | — |
| Claude Code | `~/.claude.json` | `.mcp.json` |
| Cursor | `~/.cursor/mcp.json` | `.cursor/mcp.json` |

Two notes on the fields:

- **`PYTHONPATH` is not optional.** The server is launched from whatever
  directory the client happens to be in, and `helmsmate` is not installed
  system-wide. Without it the server cannot import its own package.
- **`HELMSMATE_WORKSPACE`** is where built decks are written. It defaults to
  `<checkout>/decks`; pin it if you want decks somewhere else.

Restart the client afterwards — MCP servers are connected at start-up.

### c. The companion skill

Copy `skills/helmsmate-decks/SKILL.md` into your agent's skills directory:

| Client | Directory |
| --- | --- |
| Any (canonical) | `~/.agents/skills/helmsmate-decks/` |
| MiniMax Code | `~/.minimax/skills/helmsmate-decks/` |
| Claude Code | `~/.claude/skills/helmsmate-decks/` |
| Cursor | `~/.cursor/skills/helmsmate-decks/` |

The skill teaches the agent the deck contract and the build loop. Without it
the agent still has the tools, but you would have to say "use helmsmate" every
time.

### d. Verify

The server answers the MCP handshake and counts its own tools:

```bash
cd ~/tools/helmsmate
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | PYTHONPATH="$PWD" .venv/bin/python -m helmsmate.mcp
```

Seven tools should come back. Or let the installer do all four steps at once:

```bash
python3 scripts/install.py --client all
```

It is safe to re-run — every step overwrites rather than duplicates.

## Changing things afterwards

| Want to change | Do this |
| --- | --- |
| Where decks are written | edit `HELMSMATE_WORKSPACE` in the MCP entry |
| Which Python runs the server | edit `command` in the MCP entry |
| The skill's behaviour | edit `skills/helmsmate-decks/SKILL.md` in the checkout and re-copy it |
| A different theme or layout | ask the agent — the tools list both |

## Uninstalling

HelmsMate writes to a handful of places. Remove **only** HelmsMate's entries
from each — everything else in them belongs to your client and should stay.

| What | Where |
| --- | --- |
| The MCP server entry | the `helmsmate` key under `mcpServers` in `~/.minimax/mcp.json`, `~/.claude.json`, `~/.cursor/mcp.json`, `.mcp.json` and `.cursor/mcp.json` — whichever of these you registered with |
| The companion skill | `~/.agents/skills/helmsmate-decks/`, `~/.minimax/skills/helmsmate-decks/` (a symlink into the first), `~/.claude/skills/helmsmate-decks/` and `~/.cursor/skills/helmsmate-decks/` |
| Built decks | every `<deck-id>/` directory in the workspace — `<checkout>/decks` by default, or wherever `HELMSMATE_WORKSPACE` points |
| The checkout | `~/tools/helmsmate`, or wherever you cloned it |

Keep the `.mcp.json` and `.cursor/mcp.json` **files** if they also hold other
servers — delete only the `helmsmate` entry from them. Delete the whole file
only if HelmsMate was the only thing in it.

Nothing else is written: no system paths, no daemons, no background processes.
