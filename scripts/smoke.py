#!/usr/bin/env python3
"""HelmsMate smoke test — does the service actually work?

One command, no dependencies beyond PyYAML:

    python scripts/smoke.py

It starts the REST API on an ephemeral port, drives it the way an LLM would
(discovery, then build, then read back), runs the same loop over MCP, and
checks that what comes out is a real presentation. It prints a checklist and
exits non-zero if anything fails.

If Playwright is installed it also opens the built deck in a browser and
checks that it renders; without it, that step is skipped.

Nothing here waits forever: every network read has a deadline, so a wedged
server fails the run instead of hanging it.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from helmsmate.api import HelmsMateAPI, make_handler  # noqa: E402
from helmsmate.store import DeckStore  # noqa: E402

PASS, FAIL, SKIP = "  ✓", "  ✗", "  ·"

HTTP_TIMEOUT = 10  # seconds
MCP_TIMEOUT = 15  # seconds per response

_failures: list[str] = []


class SmokeError(Exception):
    """The run cannot continue."""


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{PASS if ok else FAIL} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        _failures.append(label)
    return ok


def skip(label: str, why: str) -> None:
    print(f"{SKIP} {label} — {why}")


def section(title: str) -> None:
    print(f"\n{title}")


def request(base: str, method: str, path: str, body: dict | None = None):
    """Call the API. Returns (status, parsed body).

    A timeout or an unreachable server comes back as status 0 with an error
    body, so a check can report it instead of the run dying.
    """
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw.decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw.decode("utf-8")
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        return 0, {"error": {"code": "unreachable", "message": str(exc)}}


DEMO_DECK = {
    "deck": {
        "title": "Smoke test deck",
        "brand": {"mark": "assets/sef-corona.svg", "word": "Smoke **Test**"},
        "chrome": False,
        "webfonts": False,
    },
    "theme": "mariners-chart",
    "slides": [
        {
            "layout": "opener",
            "context": "Opening",
            "eyebrow": "It works",
            "title": "A deck built.|over the API.",
            "lede": "Authored by a client, compiled by HelmsMate.",
            "stats": [{"big": "3", "small": "slides"}],
        },
        {
            "layout": "cards2",
            "context": "Why",
            "title": "Two cards, side by side.",
            "cards": [
                {"k": "One", "h": "Discovery", "p": "The layouts and their fields."},
                {"k": "Two", "h": "Delivery", "p": "A finished presentation."},
            ],
        },
        {
            "layout": "closer",
            "context": "End",
            "eyebrow": "Done",
            "title": "Ready to present.",
            "lede": "One HTML file, nothing missing.",
            "lede2": "No CDN, no runtime fetch.",
        },
    ],
}


def run_rest(base: str) -> str:
    """Drive the REST API. Returns the deck id it built ('' if none)."""
    section("REST — discovery")
    status, index = request(base, "GET", "/")
    check("GET / answers", status == 200 and "discovery" in str(index))

    status, doc = request(base, "GET", "/openapi.json")
    check(
        "GET /openapi.json is an OpenAPI 3.1 document",
        status == 200 and isinstance(doc, dict) and doc.get("openapi") == "3.1.0",
        f"{len(doc.get('paths', {}))} paths" if isinstance(doc, dict) else "",
    )

    status, schema = request(base, "GET", "/api/schema")
    layouts = schema.get("layouts") if isinstance(schema, dict) else None
    check(
        "GET /api/schema carries the deck contract",
        status == 200 and isinstance(layouts, list) and len(layouts) >= 5,
        f"{len(layouts)} layouts" if isinstance(layouts, list) else "",
    )
    if isinstance(layouts, list):
        notes = schema.get("authoring_notes", [])
        print(f"    {len(notes)} authoring notes")

    status, listing = request(base, "GET", "/api/layouts")
    entries = listing.get("layouts") if isinstance(listing, dict) else None
    names = [e.get("layout") for e in entries] if isinstance(entries, list) else []
    check("GET /api/layouts lists the layouts", status == 200 and "opener" in names, ", ".join(n for n in names if n))

    status, one = request(base, "GET", "/api/layouts/cards2")
    props = one.get("schema", {}).get("properties", {}) if isinstance(one, dict) else {}
    check(
        "GET /api/layouts/{name} returns that layout's schema",
        status == 200 and "cards" in props,
    )

    status, themes = request(base, "GET", "/api/themes")
    entries = themes.get("themes") if isinstance(themes, dict) else None
    theme_names = [t.get("name") for t in entries] if isinstance(entries, list) else []
    check(
        "GET /api/themes lists the themes",
        status == 200 and len(theme_names) >= 1,
        ", ".join(n for n in theme_names if n),
    )

    section("REST — building")
    status, built = request(base, "POST", "/api/decks", {"deck": DEMO_DECK})
    deck_id = built.get("deck_id", "") if isinstance(built, dict) else ""
    if not check("POST /api/decks builds a deck", status == 201 and bool(deck_id), f"HTTP {status}"):
        print(f"      {built}")
        return ""

    slides = built.get("slides", 0)
    size = built.get("bytes", 0)
    check("the response describes the deck", slides == 3 and size > 1000, f"{slides} slides, {size:,} bytes")
    check("the response carries an outline", len(built.get("outline", [])) == 3)

    status, html = request(base, "GET", f"/api/decks/{deck_id}/html")
    text = html if isinstance(html, str) else ""
    slide_count = text.count('<section class="slide"')
    check("GET /api/decks/{id}/html returns the presentation", status == 200 and bool(text))
    check("the presentation holds every slide", slide_count == 3, f"{slide_count} slides in the HTML")
    check("the deck's words made it through", "A deck built." in text and "Ready to present." in text)
    check("no placeholder was left unreplaced", "{{" not in text)
    check("the title break rendered as a line break", "A deck built.<br>over the API." in text)

    status, view = request(base, "GET", f"/decks/{deck_id}/")
    check("GET /decks/{id}/ serves it for a browser", status == 200 and "deck-head" in str(view))

    section("REST — errors and housekeeping")
    status, invalid = request(base, "POST", "/api/decks", {"deck": {"slides": [{"layout": "nope", "title": "x"}]}})
    details = invalid.get("error", {}).get("details", []) if isinstance(invalid, dict) else []
    paths = [d.get("path") for d in details if isinstance(d, dict)]
    check(
        "an invalid deck is a 422 with a path to fix",
        status == 422 and "slides[0].layout" in paths,
        ", ".join(p for p in paths if p),
    )

    status, validated = request(base, "POST", "/api/decks/validate", {"deck": DEMO_DECK})
    check("POST /api/decks/validate passes a good deck", status == 200 and validated.get("ok") is True)

    status, stored = request(base, "GET", "/api/decks")
    decks = stored.get("decks") if isinstance(stored, dict) else None
    check("GET /api/decks lists what is stored", status == 200 and isinstance(decks, list) and len(decks) >= 1)

    status, one = request(base, "GET", f"/api/decks/{deck_id}")
    slides_read = one.get("deck", {}).get("slides", []) if isinstance(one, dict) else []
    check("GET /api/decks/{id} returns the authored source", status == 200 and len(slides_read) == 3)

    # A second deck, so the one the browser check opens survives.
    status, _ = request(base, "POST", "/api/decks", {"deck": DEMO_DECK, "deck_id": "throwaway"})
    check("a second deck builds under an explicit id", status == 201)
    status, _ = request(base, "DELETE", "/api/decks/throwaway")
    check("DELETE /api/decks/{id} removes it", status == 200)
    status, _ = request(base, "GET", "/api/decks/throwaway")
    check("the removed deck is gone", status == 404)

    return deck_id


def _read_with_deadline(stream, timeout: float) -> str:
    """Read one line, or return '' if the deadline passes.

    readline() on a pipe blocks, so the read happens on a worker thread.
    """
    box: list[str] = []

    def reader() -> None:
        try:
            box.append(stream.readline())
        except Exception:  # noqa: BLE001
            box.append("")

    worker = threading.Thread(target=reader, daemon=True)
    worker.start()
    worker.join(timeout)
    return box[0] if box else ""


def run_mcp(workspace: Path) -> None:
    """Drive the MCP server over stdio, the way an LLM would."""
    section("MCP — the LLM loop")
    proc = subprocess.Popen(
        [sys.executable, "-m", "helmsmate.mcp", "--workspace", str(workspace)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO),
    )

    def rpc(method: str, params: dict | None = None, msg_id: list[int] = [0]) -> dict:
        msg_id[0] += 1
        message = {"jsonrpc": "2.0", "id": msg_id[0], "method": method}
        if params is not None:
            message["params"] = params
        try:
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise SmokeError(f"the MCP server closed the connection: {exc}") from exc
        line = _read_with_deadline(proc.stdout, MCP_TIMEOUT)
        if not line:
            # No answer in time: stop the child so the run can fail rather
            # than hang on a wedged server.
            proc.kill()
            raise SmokeError(f"no response to {method} within {MCP_TIMEOUT}s")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            # Malformed output is a failure to report, not a crash: the run
            # continues and prints its summary.
            excerpt = line.strip()[:120]
            raise SmokeError(f"malformed response to {method}: {exc} — got {excerpt!r}") from exc

    def tool(name: str, arguments: dict) -> dict:
        return rpc("tools/call", {"name": name, "arguments": arguments}).get("result", {})

    try:
        init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}).get("result", {})
        server = init.get("serverInfo", {}) if isinstance(init, dict) else {}
        check(
            "initialize negotiates a protocol",
            server.get("name") == "helmsmate" and "protocolVersion" in init,
            str(init.get("protocolVersion", "")),
        )

        tools = rpc("tools/list").get("result", {}).get("tools", [])
        names = [t.get("name") for t in tools if isinstance(t, dict)]
        check(
            "tools/list exposes the deck functions",
            {"get_deck_schema", "build_deck", "validate_deck"} <= set(names),
            ", ".join(n for n in names if n),
        )
        check(
            "every tool declares an input schema",
            all(t.get("inputSchema", {}).get("type") == "object" for t in tools if isinstance(t, dict)),
        )

        schema = tool("get_deck_schema", {}).get("structuredContent", {})
        schema_layouts = schema.get("layouts", []) if isinstance(schema, dict) else []
        check(
            "get_deck_schema returns the contract",
            isinstance(schema_layouts, list) and len(schema_layouts) >= 5,
            f"{len(schema_layouts)} layouts",
        )

        result = tool("build_deck", {"deck": DEMO_DECK})
        payload = result.get("structuredContent", {}) if isinstance(result, dict) else {}
        deck_id = payload.get("deck_id", "")
        check(
            "build_deck returns a finished presentation",
            not result.get("isError") and payload.get("slides") == 3 and bool(deck_id),
            f"{deck_id} — {payload.get('bytes', 0):,} bytes",
        )
        check("build_deck returns a URL to view it", str(payload.get("url", "")).endswith("/"))

        if deck_id:
            back = tool("read_deck", {"deck_id": deck_id}).get("structuredContent", {})
            slides = back.get("deck", {}).get("slides", []) if isinstance(back, dict) else []
            check("read_deck returns the authored source back", len(slides) == 3)

        bad = tool("build_deck", {"deck": {"slides": [{"layout": "nope"}]}})
        content = bad.get("content", []) if isinstance(bad, dict) else []
        text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
        check(
            "a bad deck comes back as an error with paths to fix",
            bool(bad.get("isError")) and "slides[0].layout" in text,
        )
    except SmokeError as exc:
        # The message carries the method and the offending output — show it
        # whole enough to diagnose from.
        check("the MCP server answered", False, str(exc)[:200])
    finally:
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()


def run_browser(html: Path) -> None:
    """Open the built deck in a browser, if Playwright is around."""
    section("Browser — does it actually render?")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        skip("render check", "Playwright not installed (uv add --dev playwright)")
        return

    if not html.exists():
        skip("render check", "no built deck to open")
        return

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(html.resolve().as_uri())
            page.wait_for_timeout(500)

            slides = page.locator(".slide").count()
            check("every slide is in the DOM", slides == 3, f"{slides} slides")

            counter = page.locator("#pageno").inner_text()
            check("the counter is centred", counter == "1 / 3", counter)

            page.click("#menu-btn")
            page.wait_for_timeout(200)
            check("the slide index opens", page.locator(".deck-menu.open").count() == 1)

            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(700)
            counter = page.locator("#pageno").inner_text()
            check("arrow keys move between slides", counter == "2 / 3", counter)

            overflow = page.evaluate(
                """() => {
                    const s = document.querySelectorAll('.slide')[1];
                    const r = s.getBoundingClientRect();
                    let max = r.right;
                    s.querySelectorAll('*').forEach(el => {
                        const b = el.getBoundingClientRect();
                        if (b.right > max) max = b.right;
                    });
                    return max - r.right;
                }"""
            )
            check("no horizontal overflow", overflow <= 1, f"{overflow:.1f}px")
            browser.close()
    except Exception as exc:  # noqa: BLE001
        check("render check", False, str(exc)[:80])


def main() -> int:
    print("HelmsMate smoke test")
    print("=" * 60)

    workspace = Path(tempfile.mkdtemp(prefix="helmsmate-smoke-"))
    store = DeckStore(workspace / "decks")
    api = HelmsMateAPI(store, base_url="")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api, quiet=True))
    port = httpd.server_address[1]
    # Now that the port is known, the API hands out URLs that actually work.
    api.base_url = f"http://127.0.0.1:{port}"
    api.mcp.base_url = api.base_url
    base = api.base_url
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    try:
        deck_id = run_rest(base)
        run_mcp(workspace)
        if deck_id:
            run_browser(store.deck_dir(deck_id) / "index.html")
        else:
            skip("render check", "the REST build did not produce a deck")
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("\n" + "=" * 60)
    if _failures:
        print(f"FAILED — {len(_failures)} check(s):")
        for name in _failures:
            print(f"  · {name}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
