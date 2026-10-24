"""MCP server — expose HelmsMate's functions to an LLM as tools.

This is the discovery surface an LLM uses: it lists the tools, reads their
input schemas, and calls them. The tools are thin wrappers over the same
library functions the REST API exposes, so the two can never drift.

Transport is JSON-RPC 2.0. :func:`stdio_main` speaks the MCP stdio transport
(newline-delimited JSON) for local clients; the REST API mounts the same
handler at ``POST /mcp`` for remote ones.

Tools
-----
``list_themes``     themes available for the deck
``list_layouts``    the layout catalog — what each layout shows and takes
``get_deck_schema`` the full contract: JSON Schema, catalog, authoring notes
``validate_deck``   check a deck, with paths and hints
``build_deck``      build a deck and return the finished presentation
``list_decks``      decks already in the workspace
``read_deck``       the authored source of a stored deck
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from . import spec, themes
from .engine import BuildError, build_html, site_chrome_warning
from .store import DeckStore, StoreError
from .validate import ERROR, validate_deck

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL = PROTOCOL_VERSIONS[0]
SERVER_NAME = "helmsmate"
SERVER_VERSION = "0.1.0"

INSTRUCTIONS = (
    "HelmsMate compiles a YAML deck into a single self-contained HTML "
    "presentation.\n\n"
    "To build a deck: call get_deck_schema to learn the contract, author a deck "
    "against it, then call build_deck. The result carries a URL and the built "
    "HTML file.\n\n"
    "Deck shape: {deck: {title, brand, footer}, theme, slides: [...]}. Each "
    "slide has a layout (opener, cards2, cards3, figure2, closer, demo) and "
    "the fields that layout consumes.\n\n"
    "If build_deck returns validation errors, read the path and hint on each "
    "one, fix the deck and call it again."
)


class ToolError(Exception):
    """A tool failed in a way the caller can fix."""


class MCPServer:
    """The tool layer, independent of transport."""

    def __init__(self, store: DeckStore | None = None, base_url: str = "") -> None:
        self.store = store or DeckStore()
        self.base_url = base_url.rstrip("/")

    # ── tool registry ──────────────────────────────────────────────────────

    def tool_definitions(self) -> list[dict[str, Any]]:
        deck_schema = spec.inline_deck_schema()
        return [
            {
                "name": "list_themes",
                "description": (
                    "List the themes a deck can use. Each theme carries its "
                    "palette, fonts and colour modes. Pick one for the deck's "
                    "'theme' field."
                ),
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "list_layouts",
                "description": (
                    "List the slide layouts. Each entry says what the layout "
                    "shows, which fields it takes (and which are required), and "
                    "gives a YAML example. Pass a layout name to get just that one."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "layout": {
                            "type": "string",
                            "enum": spec.layout_names(),
                            "description": "Optional. A single layout to describe.",
                        }
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_deck_schema",
                "description": (
                    "The complete contract for authoring a deck: JSON Schema, "
                    "the layout catalog, field conventions and authoring notes. "
                    "Call this before writing the first deck."
                ),
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "validate_deck",
                "description": (
                    "Check a deck without building it. Returns errors and "
                    "warnings, each with a path (like slides[3].cards[1].h) and "
                    "a hint on how to fix it."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "deck": {
                            "type": "object",
                            "description": "The deck to validate.",
                            **deck_schema,
                        }
                    },
                    "required": ["deck"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "build_deck",
                "description": (
                    "Build a deck and return the finished presentation: a deck "
                    "id, a URL to view it, the path of the built HTML file, the "
                    "slide outline and any warnings. Validates first — if the "
                    "deck is invalid the errors come back with paths and hints, "
                    "fix them and call again."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "deck": {
                            "type": "object",
                            "description": "The deck to build.",
                            **deck_schema,
                        },
                        "deck_id": {
                            "type": "string",
                            "description": (
                                "Optional id to store under. Generated from the "
                                "title when omitted."
                            ),
                        },
                    },
                    "required": ["deck"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_decks",
                "description": "List the decks already built and stored in the workspace.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "read_deck",
                "description": (
                    "Read the authored source of a stored deck. Returns the "
                    "deck as structured YAML-ready data plus its metadata."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "deck_id": {"type": "string", "description": "The deck to read."}
                    },
                    "required": ["deck_id"],
                    "additionalProperties": False,
                },
            },
        ]

    # ── tool implementations ───────────────────────────────────────────────

    def _tool_list_themes(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"themes": themes.list_themes(), "default": themes.DEFAULT_THEME}

    def _tool_list_layouts(self, args: dict[str, Any]) -> dict[str, Any]:
        name = args.get("layout")
        if name:
            if name not in spec.LAYOUTS:
                raise ToolError(f"Unknown layout {name!r}. One of: {', '.join(spec.layout_names())}.")
            entry = next(x for x in spec.layout_catalog() if x["layout"] == name)
            return {"layout": entry, "schema": spec.layout_schema(name)}
        return {"layouts": spec.layout_catalog()}

    def _tool_get_deck_schema(self, args: dict[str, Any]) -> dict[str, Any]:
        return spec.schema_document()

    def _tool_validate_deck(self, args: dict[str, Any]) -> dict[str, Any]:
        deck = args.get("deck")
        if not isinstance(deck, dict):
            raise ToolError("'deck' must be an object describing the deck.")
        issues = validate_deck(deck)
        errors = [i.to_dict() for i in issues if i.severity == ERROR]
        warnings = [i.to_dict() for i in issues if i.severity != ERROR]
        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "message": (
                "Deck is valid."
                if not errors
                else f"{len(errors)} error(s) — fix them and build again."
            ),
        }

    def _tool_build_deck(self, args: dict[str, Any]) -> dict[str, Any]:
        deck = args.get("deck")
        if not isinstance(deck, dict):
            raise ToolError("'deck' must be an object describing the deck.")

        issues = validate_deck(deck)
        errors = [i for i in issues if i.severity == ERROR]
        if errors:
            return {
                "message": (
                    f"The deck did not build — {len(errors)} validation error(s). "
                    "Each error has a path and a hint. Fix them and call build_deck again."
                ),
                "ok": False,
                # The tool did not produce its artefact — say so, so a client
                # branching on isError does not read a failed build as a
                # successful one.
                "is_error": True,
                "errors": [i.to_dict() for i in errors],
                "warnings": [i.to_dict() for i in issues if i.severity != ERROR],
            }

        chrome_warning = site_chrome_warning(deck)
        asset_roots = self.store.asset_roots()
        try:
            result = build_html(deck, asset_roots=asset_roots)
        except BuildError as exc:
            raise ToolError(str(exc)) from exc

        deck_id = args.get("deck_id")
        record = self.store.save(deck, result.html, deck_id=deck_id)

        return {
            "ok": True,
            "deck_id": record.id,
            "title": record.title,
            "slides": result.slides,
            "theme": result.theme,
            "bytes": record.bytes,
            "url": f"{self.base_url}/decks/{record.id}/" if self.base_url else f"/decks/{record.id}/",
            "html_path": f"{record.path}/index.html",
            "source_path": f"{record.path}/deck.yaml",
            "outline": result.outline,
            "warnings": result.warnings + ([chrome_warning] if chrome_warning else []),
            "message": (
                f"Built {result.slides} slides ({record.bytes:,} bytes). "
                f"Open {record.id}/ to view it."
            ),
        }

    def _tool_list_decks(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"decks": [r.to_dict() for r in self.store.list()]}

    def _tool_read_deck(self, args: dict[str, Any]) -> dict[str, Any]:
        deck_id = args.get("deck_id")
        if not deck_id:
            raise ToolError("'deck_id' is required.")
        try:
            record = self.store.get(deck_id)
            deck = self.store.read_deck(deck_id)
        except StoreError as exc:
            raise ToolError(str(exc)) from exc
        return {"deck": deck, "meta": record.to_dict()}

    def call_tool(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a tool and return its structured result.

        Tool failures raise :class:`ToolError` — the caller turns those into
        an MCP result with ``isError``, not a JSON-RPC error.
        """
        args = args or {}
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "list_themes": self._tool_list_themes,
            "list_layouts": self._tool_list_layouts,
            "get_deck_schema": self._tool_get_deck_schema,
            "validate_deck": self._tool_validate_deck,
            "build_deck": self._tool_build_deck,
            "list_decks": self._tool_list_decks,
            "read_deck": self._tool_read_deck,
        }
        handler = handlers.get(name)
        if handler is None:
            raise ToolError(f"Unknown tool: {name}. Known tools: {', '.join(handlers)}.")
        return handler(args)

    # ── JSON-RPC ───────────────────────────────────────────────────────────

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Handle one JSON-RPC message. Returns None for notifications."""
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params")

        if method is None:
            return self._error(msg_id, -32600, "Invalid request: no method")

        version = message.get("jsonrpc")
        if version is not None and version != "2.0":
            if is_notification:
                return None
            return self._error(msg_id, -32600, f"Unsupported JSON-RPC version: {version!r}")

        # Notifications carry no id and get no response.
        is_notification = "id" not in message

        if params is None:
            params = {}
        elif not isinstance(params, dict):
            if is_notification:
                return None
            return self._error(msg_id, -32602, "'params' must be an object")

        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in PROTOCOL_VERSIONS else DEFAULT_PROTOCOL
            result: Any = {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": INSTRUCTIONS,
            }
        elif method in ("notifications/initialized", "notifications/cancelled"):
            return None
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": self.tool_definitions()}
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments")
            if args is None:
                args = {}
            elif not isinstance(args, dict):
                if is_notification:
                    return None
                return self._error(msg_id, -32602, "'arguments' must be an object")
            if not name:
                if is_notification:
                    return None
                return self._error(msg_id, -32602, "tools/call requires a tool name")
            try:
                payload = self.call_tool(name, args)
            except ToolError as exc:
                result = {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                }
            else:
                is_error = bool(isinstance(payload, dict) and payload.get("is_error"))
                result = {
                    "content": [
                        {"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}
                    ],
                    "structuredContent": payload,
                    "isError": is_error,
                }
        elif method == "prompts/list":
            result = {"prompts": []}
        elif method == "resources/list":
            result = {"resources": []}
        else:
            if is_notification:
                return None
            return self._error(msg_id, -32601, f"Method not found: {method}")

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def stdio_main(argv: list[str] | None = None) -> int:
    """Run the MCP server over stdio (newline-delimited JSON-RPC)."""
    argv = argv if argv is not None else sys.argv[1:]
    workspace = None
    base_url = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--workspace" and i + 1 < len(argv):
            workspace = argv[i + 1]
            i += 2
        elif argv[i] == "--base-url" and i + 1 < len(argv):
            base_url = argv[i + 1]
            i += 2
        else:
            i += 1

    server = MCPServer(DeckStore(workspace) if workspace else DeckStore(), base_url=base_url)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response: dict[str, Any] | None = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        else:
            response = server.handle_message(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(stdio_main())
