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
"""

from __future__ import annotations

import json
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
_failures: list[str] = []


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
    """Call the API. Returns (status, parsed body)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
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


def run_rest(base: str) -> tuple[str, str]:
    """Drive the REST API. Returns (deck_id, deck_dir)."""
    section("REST — discovery")
    status, index = request(base, "GET", "/")
    check("GET / answers", status == 200 and "discovery" in index)

    status, doc = request(base, "GET", "/openapi.json")
    check(
        "GET /openapi.json is an OpenAPI 3.1 document",
        status == 200 and doc.get("openapi") == "3.1.0",
        f"{len(doc.get('paths', {}))} paths",
    )

    status, schema = request(base, "GET", "/api/schema")
    check(
        "GET /api/schema carries the deck contract",
        status == 200 and "deck_schema" in schema and len(schema["layouts"]) >= 5,
        f"{len(schema['layouts'])} layouts, {len(schema['authoring_notes'])} notes",
    )

    status, layouts = request(base, "GET", "/api/layouts")
    names = [entry["layout"] for entry in layouts.get("layouts", [])]
    check("GET /api/layouts lists the layouts", status == 200 and "opener" in names, ", ".join(names))

    status, one = request(base, "GET", "/api/layouts/cards2")
    check(
        "GET /api/layouts/{name} returns that layout's schema",
        status == 200 and "cards" in one.get("schema", {}).get("properties", {}),
    )

    status, themes = request(base, "GET", "/api/themes")
    check(
        "GET /api/themes lists the themes",
        status == 200 and len(themes.get("themes", [])) >= 1,
        ", ".join(t["name"] for t in themes.get("themes", [])),
    )

    section("REST — building")
    status, built = request(base, "POST", "/api/decks", {"deck": DEMO_DECK})
    if not check("POST /api/decks builds a deck", status == 201, f"HTTP {status}"):
        print(f"      {built}")
        return "", ""
    deck_id = built["deck_id"]
    check(
        "the response describes the deck",
        built["slides"] == 3 and built["bytes"] > 1000,
        f"{built['slides']} slides, {built['bytes']:,} bytes",
    )
    check("the response carries an outline", len(built.get("outline", [])) == 3)

    status, html = request(base, "GET", f"/api/decks/{deck_id}/html")
    check("GET /api/decks/{id}/html returns the presentation", status == 200)
    check(
        "the presentation holds every slide",
        html.count('<section class="slide"') == 3,
        f"{html.count('<section class=\"slide\"')} slides in the HTML",
    )
    check(
        "the deck's words made it through",
        "A deck built." in html and "Ready to present." in html,
    )
    check("no placeholder was left unreplaced", "{{" not in html)
    check("the title break rendered as a line break", "A deck built.<br>over the API." in html)

    status, view = request(base, "GET", f"/decks/{deck_id}/")
    check("GET /decks/{id}/ serves it for a browser", status == 200 and "deck-head" in view)

    section("REST — errors and housekeeping")
    status, invalid = request(
        base, "POST", "/api/decks", {"deck": {"slides": [{"layout": "nope", "title": "x"}]}}
    )
    paths = [d.get("path") for d in invalid.get("error", {}).get("details", [])]
    check(
        "an invalid deck is a 422 with a path to fix",
        status == 422 and "slides[0].layout" in paths,
        ", ".join(paths),
    )

    status, validated = request(base, "POST", "/api/decks/validate", {"deck": DEMO_DECK})
    check("POST /api/decks/validate passes a good deck", status == 200 and validated["ok"])

    status, listed = request(base, "GET", "/api/decks")
    check("GET /api/decks lists what is stored", status == 200 and len(listed["decks"]) >= 1)

    status, one = request(base, "GET", f"/api/decks/{deck_id}")
    check(
        "GET /api/decks/{id} returns the authored source",
        status == 200 and len(one["deck"]["slides"]) == 3,
    )

    # A second deck, so the one the browser check opens survives.
    status, spare = request(base, "POST", "/api/decks", {"deck": DEMO_DECK, "deck_id": "throwaway"})
    check("a second deck builds under an explicit id", status == 201)
    status, _ = request(base, "DELETE", "/api/decks/throwaway")
    check("DELETE /api/decks/{id} removes it", status == 200)
    status, _ = request(base, "GET", "/api/decks/throwaway")
    check("the removed deck is gone", status == 404)

    return deck_id, ""


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
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    def tool(name: str, arguments: dict) -> dict:
        return rpc("tools/call", {"name": name, "arguments": arguments})["result"]

    try:
        init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})["result"]
        check(
            "initialize negotiates a protocol",
            init["serverInfo"]["name"] == "helmsmate" and "protocolVersion" in init,
            init["protocolVersion"],
        )

        tools = rpc("tools/list")["result"]["tools"]
        names = [t["name"] for t in tools]
        check(
            "tools/list exposes the deck functions",
            {"get_deck_schema", "build_deck", "validate_deck"} <= set(names),
            ", ".join(names),
        )
        check(
            "every tool declares an input schema",
            all(t.get("inputSchema", {}).get("type") == "object" for t in tools),
        )

        schema = tool("get_deck_schema", {})["structuredContent"]
        check(
            "get_deck_schema returns the contract",
            "deck_schema" in schema and len(schema["layouts"]) >= 5,
        )

        result = tool("build_deck", {"deck": DEMO_DECK})
        payload = result["structuredContent"]
        check(
            "build_deck returns a finished presentation",
            not result["isError"] and payload["slides"] == 3,
            f"{payload.get('deck_id')} — {payload.get('bytes', 0):,} bytes",
        )
        check("build_deck returns a URL to view it", str(payload.get("url", "")).endswith("/"))

        back = tool("read_deck", {"deck_id": payload["deck_id"]})["structuredContent"]
        check(
            "read_deck returns the authored source back",
            len(back["deck"]["slides"]) == 3,
        )

        bad = tool("build_deck", {"deck": {"slides": [{"layout": "nope"}]}})
        check(
            "a bad deck comes back as an error with paths to fix",
            bad["isError"] and "slides[0].layout" in bad["content"][0]["text"],
        )
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


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

            check(
                "the counter is centred",
                page.locator("#pageno").inner_text() == "1 / 3",
                page.locator("#pageno").inner_text(),
            )

            page.click("#menu-btn")
            page.wait_for_timeout(200)
            check("the slide index opens", page.locator(".deck-menu.open").count() == 1)

            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(700)
            check(
                "arrow keys move between slides",
                page.locator("#pageno").inner_text() == "2 / 3",
                page.locator("#pageno").inner_text(),
            )

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
    api = HelmsMateAPI(store, base_url="http://127.0.0.1:8787")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api, quiet=True))
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    try:
        deck_id, _ = run_rest(base)
        run_mcp(workspace)
        run_browser(store.deck_dir(deck_id) / "index.html")
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
