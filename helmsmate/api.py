"""REST API — HelmsMate as a service other software can call.

Standard library only: ``http.server`` plus JSON. No framework, no runtime
dependency — the same constraint the deck output lives under.

Discovery
---------
``GET /openapi.json``   OpenAPI 3.1 description of every endpoint.
``GET /api/schema``     The deck contract: JSON Schema, layout catalog, notes.
``GET /api/layouts``    What each layout shows and takes.
``GET /api/themes``     Themes available for a deck.

The deck endpoints
------------------
``POST /api/decks``            Build and store a deck; returns a URL to it.
``POST /api/decks/validate``   Check a deck without building it.
``GET  /api/decks``            List stored decks.
``GET  /api/decks/{id}``       One deck: metadata plus authored source.
``GET  /api/decks/{id}/yaml``  The authored source, as YAML.
``GET  /api/decks/{id}/html``  The built presentation, as HTML.
``GET  /decks/{id}/``          The built presentation, to view in a browser.
``DELETE /api/decks/{id}``     Remove a stored deck.

``POST /mcp`` speaks the same tools as the MCP server over JSON-RPC, so an
LLM can use either transport.

Run it::

    python -m helmsmate.api --port 8787
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import yaml

from . import spec, themes
from .engine import BuildError, build_html, site_chrome_warning
from .mcp import MCPServer
from .store import DeckStore, StoreError
from .validate import ERROR, validate_deck

MAX_BODY_BYTES = 32 * 1024 * 1024  # 32 MB — decks with inline figures

Handler = Callable[["Request"], "Response"]


class Request:
    """One inbound HTTP request."""

    def __init__(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
        headers: Any,
        body: bytes,
        params: dict[str, str] | None = None,
    ) -> None:
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.body = body
        self.params = params or {}

    def json(self) -> Any:
        if not self.body:
            return {}
        try:
            return json.loads(self.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise APIError(400, "invalid_json", f"Request body is not valid JSON: {exc}")

    def body_payload(self) -> Any:
        """Parse the body as JSON, falling back to YAML."""
        raw = self.body.decode("utf-8", "replace").strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            try:
                return yaml.safe_load(raw)
            except yaml.YAMLError as exc:
                raise APIError(400, "invalid_deck", f"Body is neither JSON nor YAML: {exc}")

    def deck_and_id_from_body(self) -> tuple[dict[str, Any], str | None]:
        """The deck in the body, and the deck id to store it under.

        Accepts ``{"deck": {...}, "deck_id": "x"}``, a bare deck object
        (which may carry its own ``deck_id``), or the YAML text of a deck.
        """
        payload = self.body_payload()

        deck_id: str | None = None
        deck: Any = payload

        if isinstance(payload, dict) and "slides" not in payload:
            inner = payload.get("deck")
            if isinstance(inner, (dict, str)):
                deck = inner
                if isinstance(payload.get("deck_id"), str):
                    deck_id = payload["deck_id"]

        if isinstance(deck, str):
            try:
                deck = yaml.safe_load(deck)
            except yaml.YAMLError as exc:
                raise APIError(400, "invalid_yaml", f"Could not parse deck YAML: {exc}")

        if not isinstance(deck, dict):
            raise APIError(400, "invalid_deck", "Expected a deck object or {'deck': {...}}.")

        # deck_id addresses the result; it is not part of the deck.
        if deck_id is None and isinstance(deck.get("deck_id"), str):
            deck_id = deck["deck_id"]
        deck = {k: v for k, v in deck.items() if k != "deck_id"}
        return deck, deck_id

    def deck_from_body(self) -> dict[str, Any]:
        """The deck in the body."""
        return self.deck_and_id_from_body()[0]


class Response:
    """One outbound HTTP response."""

    def __init__(
        self,
        status: int = 200,
        body: Any = None,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
        raw: bytes | str | None = None,
    ) -> None:
        self.status = status
        self.content_type = content_type
        self.headers = headers or {}
        if raw is not None:
            self.raw = raw.encode("utf-8") if isinstance(raw, str) else raw
        elif body is None:
            self.raw = b""
        elif isinstance(body, (dict, list)):
            self.raw = json.dumps(body, indent=2, ensure_ascii=False).encode("utf-8")
        else:
            self.raw = str(body).encode("utf-8")


class APIError(Exception):
    """An error that maps to an HTTP status."""

    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details

    def to_response(self) -> Response:
        payload: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.details is not None:
            payload["error"]["details"] = self.details
        return Response(self.status, payload)


# ── OpenAPI ────────────────────────────────────────────────────────────────


def openapi_document(base_url: str = "") -> dict[str, Any]:
    """OpenAPI 3.1 description of the API."""
    server = {"url": base_url or "/"} if base_url else {}
    deck_schema = spec.inline_deck_schema()
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "HelmsMate API",
            "version": "0.1.0",
            "summary": "Compile YAML decks into self-contained HTML presentations.",
            "description": (
                "HelmsMate turns one YAML deck into a single self-contained HTML "
                "presentation (HTML + CSS + JS + inlined SVG, no runtime fetch).\n\n"
                "Start with GET /api/schema for the deck contract, then POST "
                "/api/decks. The same functions are exposed to LLMs as MCP tools "
                "at POST /mcp."
            ),
            "license": {"name": "MIT"},
        },
        "servers": [server] if server else [],
        "tags": [
            {"name": "discovery", "description": "What HelmsMate can do and how to ask for it."},
            {"name": "decks", "description": "Build, read and remove presentations."},
            {"name": "mcp", "description": "MCP tool calling over JSON-RPC."},
        ],
        "paths": {
            "/": {
                "get": {
                    "tags": ["discovery"],
                    "summary": "Service index",
                    "operationId": "getIndex",
                    "responses": {"200": {"description": "Endpoint index."}},
                }
            },
            "/openapi.json": {
                "get": {
                    "tags": ["discovery"],
                    "summary": "This document",
                    "operationId": "getOpenapi",
                    "responses": {"200": {"description": "OpenAPI 3.1 document."}},
                }
            },
            "/api/schema": {
                "get": {
                    "tags": ["discovery"],
                    "summary": "The deck contract",
                    "description": (
                        "JSON Schema for a deck, the layout catalog, field "
                        "conventions and authoring notes. This is what an LLM "
                        "reads to author a deck."
                    ),
                    "operationId": "getSchema",
                    "responses": {"200": {"description": "Schema document."}},
                }
            },
            "/api/layouts": {
                "get": {
                    "tags": ["discovery"],
                    "summary": "Layout catalog",
                    "operationId": "listLayouts",
                    "responses": {"200": {"description": "Every layout and its fields."}},
                }
            },
            "/api/layouts/{layout}": {
                "get": {
                    "tags": ["discovery"],
                    "summary": "One layout",
                    "operationId": "getLayout",
                    "parameters": [
                        {
                            "name": "layout",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "enum": spec.layout_names()},
                        }
                    ],
                    "responses": {
                        "200": {"description": "Layout detail."},
                        "404": {"description": "No such layout."},
                    },
                }
            },
            "/api/themes": {
                "get": {
                    "tags": ["discovery"],
                    "summary": "Theme catalog",
                    "operationId": "listThemes",
                    "responses": {"200": {"description": "Available themes."}},
                }
            },
            "/api/decks": {
                "get": {
                    "tags": ["decks"],
                    "summary": "List stored decks",
                    "operationId": "listDecks",
                    "responses": {"200": {"description": "Stored decks, newest first."}},
                },
                "post": {
                    "tags": ["decks"],
                    "summary": "Build a deck",
                    "description": (
                        "Validate and build a deck, then store it. Returns the "
                        "deck id, a URL to view it and the slide outline. An "
                        "invalid deck returns 422 with per-field errors and hints."
                    ),
                    "operationId": "buildDeck",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "deck": deck_schema,
                                        "deck_id": {"type": "string"},
                                    },
                                    "required": ["deck"],
                                }
                            },
                            "application/yaml": {"schema": {"type": "string"}},
                            "text/yaml": {"schema": {"type": "string"}},
                        },
                    },
                    "responses": {
                        "201": {"description": "Built and stored."},
                        "422": {"description": "The deck has validation errors."},
                        "400": {"description": "The body could not be read as a deck."},
                    },
                },
            },
            "/api/decks/validate": {
                "post": {
                    "tags": ["decks"],
                    "summary": "Validate a deck",
                    "operationId": "validateDeck",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"deck": deck_schema},
                                    "required": ["deck"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Errors and warnings."}},
                }
            },
            "/api/decks/{deck_id}": {
                "get": {
                    "tags": ["decks"],
                    "summary": "Read a deck",
                    "operationId": "getDeck",
                    "parameters": [
                        {
                            "name": "deck_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {"description": "Deck metadata and authored source."},
                        "404": {"description": "No such deck."},
                    },
                },
                "delete": {
                    "tags": ["decks"],
                    "summary": "Delete a deck",
                    "operationId": "deleteDeck",
                    "parameters": [
                        {
                            "name": "deck_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {"description": "Deleted."},
                        "404": {"description": "No such deck."},
                    },
                },
            },
            "/api/decks/{deck_id}/yaml": {
                "get": {
                    "tags": ["decks"],
                    "summary": "The authored source",
                    "operationId": "getDeckYaml",
                    "parameters": [
                        {"name": "deck_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "YAML source."}},
                }
            },
            "/api/decks/{deck_id}/html": {
                "get": {
                    "tags": ["decks"],
                    "summary": "The built presentation",
                    "operationId": "getDeckHtml",
                    "parameters": [
                        {"name": "deck_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "The self-contained HTML."}},
                }
            },
            "/decks/{deck_id}/": {
                "get": {
                    "tags": ["decks"],
                    "summary": "View a built presentation",
                    "operationId": "viewDeck",
                    "parameters": [
                        {"name": "deck_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "The presentation, for browsers."}},
                }
            },
            "/mcp": {
                "post": {
                    "tags": ["mcp"],
                    "summary": "MCP tool calling (JSON-RPC 2.0)",
                    "description": (
                        "The MCP server: 'initialize', 'tools/list', 'tools/call'. "
                        "The same tools the stdio transport exposes."
                    ),
                    "operationId": "mcp",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                    "responses": {"200": {"description": "JSON-RPC response."}},
                }
            },
        },
        "components": {
            "schemas": {
                "Deck": deck_schema,
                "Error": {
                    "type": "object",
                    "properties": {
                        "error": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "details": {},
                            },
                            "required": ["code", "message"],
                        }
                    },
                    "required": ["error"],
                },
                "ValidationIssue": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Where the problem is."},
                        "message": {"type": "string"},
                        "hint": {"type": "string", "description": "How to fix it."},
                        "severity": {"type": "string", "enum": ["error", "warning"]},
                    },
                    "required": ["path", "message"],
                },
            }
        },
    }


# ── The API ────────────────────────────────────────────────────────────────


class HelmsMateAPI:
    """Routing and handlers."""

    def __init__(self, store: DeckStore | None = None, base_url: str = "") -> None:
        self.store = store or DeckStore()
        self.base_url = base_url.rstrip("/")
        self.mcp = MCPServer(self.store, base_url=self.base_url)
        self.routes: list[tuple[str, re.Pattern[str], Handler]] = []
        self._register()

    def _register(self) -> None:
        add = lambda method, pattern, handler: self.routes.append(  # noqa: E731
            (method, re.compile(f"^{pattern}$"), handler)
        )
        add("GET", r"/", self.index)
        add("GET", r"/openapi\.json", self.openapi)
        add("GET", r"/api/schema", self.schema)
        add("GET", r"/api/layouts", self.list_layouts)
        add("GET", r"/api/layouts/(?P<layout>[A-Za-z0-9_-]+)", self.get_layout)
        add("GET", r"/api/themes", self.list_themes)
        add("GET", r"/api/decks", self.list_decks)
        add("POST", r"/api/decks", self.build_deck)
        add("POST", r"/api/decks/validate", self.validate_deck)
        # 'validate' is a reserved path segment, not a deck id.
        deck_id = r"(?P<deck_id>(?!validate$)[A-Za-z0-9._-]+)"
        add("GET", rf"/api/decks/{deck_id}", self.get_deck)
        add("DELETE", rf"/api/decks/{deck_id}", self.delete_deck)
        add("GET", rf"/api/decks/{deck_id}/yaml", self.get_deck_yaml)
        add("GET", rf"/api/decks/{deck_id}/html", self.get_deck_html)
        add("GET", r"/decks/(?P<deck_id>[A-Za-z0-9._-]+)(?:/\d*)?/?", self.view_deck)
        add("POST", r"/mcp", self.mcp_endpoint)

    # ── dispatch ───────────────────────────────────────────────────────────

    def handle(self, request: Request) -> Response:
        allowed: set[str] = set()
        # HEAD is GET without a body — the handler drops the payload.
        method = "GET" if request.method == "HEAD" else request.method
        for route_method, pattern, handler in self.routes:
            match = pattern.match(request.path)
            if not match:
                continue
            if route_method != method:
                allowed.add(route_method)
                continue
            request.params = dict(match.groupdict())
            return handler(request)
        if allowed:
            raise APIError(
                405,
                "method_not_allowed",
                f"{request.method} is not allowed here. Try: {', '.join(sorted(allowed))}.",
            )
        raise APIError(404, "not_found", f"No route for {request.path}.")

    # ── discovery ──────────────────────────────────────────────────────────

    def index(self, request: Request) -> Response:
        return Response(
            200,
            {
                "service": "HelmsMate API",
                "version": "0.1.0",
                "description": (
                    "Compile YAML decks into single self-contained HTML presentations."
                ),
                "discovery": {
                    "openapi": "/openapi.json",
                    "deck_schema": "/api/schema",
                    "layouts": "/api/layouts",
                    "themes": "/api/themes",
                },
                "decks": {
                    "build": "POST /api/decks",
                    "validate": "POST /api/decks/validate",
                    "list": "GET /api/decks",
                    "read": "GET /api/decks/{id}",
                    "source": "GET /api/decks/{id}/yaml",
                    "html": "GET /api/decks/{id}/html",
                    "view": "GET /decks/{id}/",
                    "delete": "DELETE /api/decks/{id}",
                },
                "llm": {
                    "mcp": "POST /mcp (JSON-RPC 2.0)",
                    "tools": [
                        t["name"] for t in self.mcp.tool_definitions()
                    ],
                    "stdio": "python -m helmsmate.mcp",
                },
            },
        )

    def openapi(self, request: Request) -> Response:
        return Response(200, openapi_document(self.base_url))

    def schema(self, request: Request) -> Response:
        return Response(200, spec.schema_document())

    def list_layouts(self, request: Request) -> Response:
        return Response(200, {"layouts": spec.layout_catalog()})

    def get_layout(self, request: Request) -> Response:
        name = request.params.get("layout", "")
        if name not in spec.LAYOUTS:
            raise APIError(
                404,
                "unknown_layout",
                f"Unknown layout {name!r}. One of: {', '.join(spec.layout_names())}.",
            )
        entry = next(x for x in spec.layout_catalog() if x["layout"] == name)
        return Response(200, {"layout": entry, "schema": spec.layout_schema(name)})

    def list_themes(self, request: Request) -> Response:
        return Response(
            200, {"themes": themes.list_themes(), "default": themes.DEFAULT_THEME}
        )

    # ── decks ──────────────────────────────────────────────────────────────

    def list_decks(self, request: Request) -> Response:
        return Response(200, {"decks": [r.to_dict() for r in self.store.list()]})

    def build_deck(self, request: Request) -> Response:
        deck, deck_id = request.deck_and_id_from_body()
        issues = validate_deck(deck)
        errors = [i.to_dict() for i in issues if i.severity == ERROR]
        warnings = [i.to_dict() for i in issues if i.severity != ERROR]

        if errors:
            raise APIError(
                422,
                "invalid_deck",
                f"The deck has {len(errors)} validation error(s). Each error has a path and a hint.",
                errors,
            )

        chrome_warning = site_chrome_warning(deck)
        asset_roots = self.store.asset_roots()
        try:
            result = build_html(deck, asset_roots=asset_roots)
        except BuildError as exc:
            raise APIError(400, "build_failed", str(exc)) from exc

        try:
            record = self.store.save(deck, result.html, deck_id=deck_id)
        except StoreError as exc:
            raise APIError(400, "invalid_deck_id", str(exc)) from exc

        return Response(
            201,
            {
                "deck_id": record.id,
                "title": record.title,
                "slides": result.slides,
                "theme": result.theme,
                "bytes": record.bytes,
                "url": f"{self.base_url}/decks/{record.id}/",
                "html_path": f"{record.path}/index.html",
                "source_path": f"{record.path}/deck.yaml",
                "outline": result.outline,
                "warnings": warnings,
                "build_warnings": result.warnings + ([chrome_warning] if chrome_warning else []),
            },
            headers={"Location": f"/api/decks/{record.id}"},
        )

    def validate_deck(self, request: Request) -> Response:
        deck = request.deck_from_body()
        issues = validate_deck(deck)
        errors = [i.to_dict() for i in issues if i.severity == ERROR]
        warnings = [i.to_dict() for i in issues if i.severity != ERROR]
        return Response(
            200,
            {
                "ok": not errors,
                "errors": errors,
                "warnings": warnings,
                "message": (
                    "Deck is valid." if not errors else f"{len(errors)} error(s) to fix."
                ),
            },
        )

    def get_deck(self, request: Request) -> Response:
        deck_id = request.params.get("deck_id", "")
        try:
            record = self.store.get(deck_id)
            deck = self.store.read_deck(deck_id)
        except StoreError as exc:
            raise APIError(404, "not_found", str(exc)) from exc
        return Response(200, {"meta": record.to_dict(), "deck": deck})

    def delete_deck(self, request: Request) -> Response:
        deck_id = request.params.get("deck_id", "")
        try:
            deleted = self.store.delete(deck_id)
        except StoreError as exc:
            raise APIError(400, "invalid_deck_id", str(exc)) from exc
        if not deleted:
            raise APIError(404, "not_found", f"No such deck: {deck_id}")
        return Response(200, {"deleted": deck_id})

    def get_deck_yaml(self, request: Request) -> Response:
        deck_id = request.params.get("deck_id", "")
        try:
            text = self.store.read_yaml(deck_id)
        except StoreError as exc:
            raise APIError(404, "not_found", str(exc)) from exc
        return Response(200, text, content_type="text/yaml; charset=utf-8")

    def get_deck_html(self, request: Request) -> Response:
        deck_id = request.params.get("deck_id", "")
        try:
            html = self.store.read_html(deck_id)
        except StoreError as exc:
            raise APIError(404, "not_found", str(exc)) from exc
        return Response(
            200,
            None,
            content_type="text/html; charset=utf-8",
            raw=html,
            headers={"Content-Security-Policy": DECK_CSP},
        )

    def view_deck(self, request: Request) -> Response:
        deck_id = request.params.get("deck_id", "")
        try:
            html = self.store.read_html(deck_id)
        except StoreError as exc:
            raise APIError(404, "not_found", str(exc)) from exc
        return Response(
            200,
            None,
            content_type="text/html; charset=utf-8",
            raw=html,
            headers={"Content-Security-Policy": DECK_CSP},
        )

    # ── MCP ────────────────────────────────────────────────────────────────

    def mcp_endpoint(self, request: Request) -> Response:
        payload = request.json()
        messages = payload if isinstance(payload, list) else [payload]
        responses = []
        for message in messages:
            if not isinstance(message, dict):
                responses.append(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
                )
                continue
            response = self.mcp.handle_message(message)
            if response is not None:
                responses.append(response)
        if not responses:
            # MCP: a notification-only request is accepted and answered with
            # 202 and no body.
            return Response(202, None)
        return Response(200, responses[0] if isinstance(payload, dict) else responses)


# ── HTTP plumbing ──────────────────────────────────────────────────────────


# A built deck is content, and the content may carry script. Served from the
# API's own origin, that script could otherwise call the API itself. The
# policy keeps the deck self-contained: it renders, but it does not phone
# home. Inline script and style stay allowed — the deck's own navigation is
# inline.
DECK_CSP = (
    "default-src 'self' data: blob:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "img-src 'self' data: blob:; "
    "media-src 'self' data: blob:; "
    "connect-src 'none'; "
    "frame-src 'none'; "
    "form-action 'none'"
)


class HelmsMateServer(ThreadingHTTPServer):
    """The HTTP server.

    A client that hangs up mid-request is normal, not a server fault — those
    are dropped rather than printed as a traceback.
    """

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        exc = sys.exc_info()[0]
        if exc is not None and issubclass(
            exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)
        ):
            return
        super().handle_error(request, client_address)


def make_handler(
    api: HelmsMateAPI,
    token: str | None = None,
    quiet: bool = False,
    allow_origin: str | None = None,
):
    if token is not None and not token.strip():
        # An empty token would silently disable authentication while the
        # operator believes the service is locked.
        raise ValueError("token must be a non-empty string")
    class Handler(BaseHTTPRequestHandler):
        server_version = "HelmsMate/0.1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            if quiet:
                return
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        # ── helpers ──
        def _send(self, response: Response) -> None:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if allow_origin:
                self.send_header("Access-Control-Allow-Origin", allow_origin)
                self.send_header("Vary", "Origin")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Authorization, Content-Type, X-Helmsmate-Token",
                )
                self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            for key, value in response.headers.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.raw)

        def _authorised(self) -> bool:
            if token is None:
                return True
            header = self.headers.get("Authorization", "")
            if header[:7].lower() == "bearer ":
                presented = header[7:].strip()
            else:
                presented = self.headers.get("X-Helmsmate-Token", "").strip()
            # Constant-time: a token check that leaks its length or a prefix
            # is a token check that can be attacked one byte at a time.
            # Bytes, not str: compare_digest rejects non-ASCII strings.
            return secrets.compare_digest(presented.encode("utf-8"), token.encode("utf-8"))

        def _read_body(self) -> bytes:
            encoding = (self.headers.get("Transfer-Encoding") or "").lower()
            if "chunked" in encoding:
                # We do not decode chunked bodies. Closing the connection is
                # the only way to keep the stream in sync.
                self.close_connection = True
                raise APIError(
                    411,
                    "length_required",
                    "Chunked request bodies are not supported; send Content-Length.",
                )
            raw_length = self.headers.get("Content-Length") or 0
            try:
                length = int(raw_length)
            except (TypeError, ValueError):
                raise APIError(400, "bad_request", "Content-Length is not a number.")
            if length < 0:
                raise APIError(400, "bad_request", "Content-Length is negative.")
            if length > MAX_BODY_BYTES:
                raise APIError(413, "body_too_large", f"Body exceeds {MAX_BODY_BYTES} bytes.")
            return self.rfile.read(length) if length else b""

        def _dispatch(self) -> None:
            parsed = urlparse(self.path)
            try:
                # Read the body first: leaving it in the socket desyncs the
                # next request on a keep-alive connection.
                body = self._read_body()
                if not self._authorised():
                    raise APIError(401, "unauthorized", "A valid token is required.")
                request = Request(
                    self.command,
                    parsed.path.rstrip("/") or "/",
                    parse_qs(parsed.query),
                    self.headers,
                    body,
                )
                response = api.handle(request)
            except APIError as exc:
                response = exc.to_response()
            except Exception as exc:  # noqa: BLE001 — never leak internals to the client
                # The detail goes to the server log; the client gets the shape.
                sys.stderr.write(f"helmsmate: unhandled error: {exc!r}\n")
                response = Response(
                    500,
                    {"error": {"code": "internal_error", "message": "The server hit an unexpected error."}},
                )
            self._send(response)

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch()

        def do_HEAD(self) -> None:  # noqa: N802
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch()

        def do_DELETE(self) -> None:  # noqa: N802
            self._dispatch()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send(Response(204))

    return Handler


def serve(
    host: str = "127.0.0.1",
    port: int = 8787,
    workspace: Path | None = None,
    token: str | None = None,
    allow_origin: str | None = None,
) -> None:
    """Run the API server until interrupted."""
    store = DeckStore(workspace)
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    base_url = f"http://{display_host}:{port}"
    api = HelmsMateAPI(store, base_url=base_url)
    httpd = HelmsMateServer((host, port), make_handler(api, token, allow_origin=allow_origin))
    print(f"HelmsMate API on {base_url}")
    print(f"  workspace : {store.workspace}")
    print(f"  discovery : {base_url}/openapi.json")
    print(f"  schema    : {base_url}/api/schema")
    print(f"  mcp       : {base_url}/mcp")
    if token:
        print("  auth      : bearer token required")
    if allow_origin:
        print(f"  cors      : {allow_origin}")
    else:
        print("  cors      : off (browser clients need --allow-origin)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HelmsMate REST API")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787, help="Port (default 8787)")
    parser.add_argument("--workspace", default=None, help="Where decks are stored")
    parser.add_argument("--token", default=None, help="Require this bearer token")
    parser.add_argument(
        "--allow-origin",
        default=None,
        help="Send this CORS origin header (default: none — a local service should not answer '*')",
    )
    args = parser.parse_args(argv)
    serve(
        host=args.host,
        port=args.port,
        workspace=Path(args.workspace) if args.workspace else None,
        token=args.token,
        allow_origin=args.allow_origin,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
