"""The MCP layer — the surface an LLM actually touches."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
from pathlib import Path

# Direct execution (python tests/test_x.py) needs the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fixtures import REPO, minimal_deck  # noqa: F401

from helmsmate.mcp import MCPServer
from helmsmate.store import DeckStore


class TestMCP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = MCPServer(DeckStore(Path(self.tmp.name)), base_url="http://127.0.0.1:8787")

    def tearDown(self):
        self.tmp.cleanup()

    def rpc(self, method, params=None, msg_id=1):
        message = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            message["params"] = params
        return self.server.handle_message(message)

    # ── protocol ───────────────────────────────────────────────────────────

    def test_initialize(self):
        response = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "helmsmate")
        self.assertIn("tools", result["capabilities"])
        self.assertTrue(result["instructions"])

    def test_initialize_falls_back_for_unknown_versions(self):
        response = self.rpc("initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")

    def test_notification_gets_no_response(self):
        self.assertIsNone(
            self.server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )

    def test_unknown_method_is_a_json_rpc_error(self):
        response = self.rpc("does/not/exist")
        self.assertEqual(response["error"]["code"], -32601)

    def test_ping(self):
        self.assertEqual(self.rpc("ping")["result"], {})

    # ── tools ──────────────────────────────────────────────────────────────

    def test_tools_list(self):
        tools = self.rpc("tools/list")["result"]["tools"]
        names = [t["name"] for t in tools]
        for expected in (
            "list_themes",
            "list_layouts",
            "get_deck_schema",
            "validate_deck",
            "build_deck",
            "list_decks",
            "read_deck",
        ):
            self.assertIn(expected, names)

    def test_every_tool_declares_a_usable_schema(self):
        for tool in self.rpc("tools/list")["result"]["tools"]:
            self.assertTrue(tool["description"])
            schema = tool["inputSchema"]
            self.assertEqual(schema["type"], "object")
            self.assertIn("properties", schema)
            blob = json.dumps(schema)
            self.assertNotIn("$ref", blob, f"{tool['name']} has a dangling $ref")

    def test_build_deck_tool_carries_the_deck_schema(self):
        tools = {t["name"]: t for t in self.rpc("tools/list")["result"]["tools"]}
        deck_schema = tools["build_deck"]["inputSchema"]["properties"]["deck"]
        self.assertIn("slides", deck_schema["properties"])
        self.assertEqual(deck_schema["properties"]["theme"]["type"], "string")

    def test_call_list_themes(self):
        result = self.rpc(
            "tools/call", {"name": "list_themes", "arguments": {}}
        )["result"]
        payload = result["structuredContent"]
        self.assertIn("mariners-chart", [t["name"] for t in payload["themes"]])

    def test_call_get_deck_schema(self):
        payload = self.rpc(
            "tools/call", {"name": "get_deck_schema", "arguments": {}}
        )["result"]["structuredContent"]
        self.assertIn("deck_schema", payload)
        self.assertEqual(len(payload["layouts"]), 6)

    def test_call_list_layouts_for_one_layout(self):
        payload = self.rpc(
            "tools/call", {"name": "list_layouts", "arguments": {"layout": "cards2"}}
        )["result"]["structuredContent"]
        self.assertEqual(payload["layout"]["layout"], "cards2")

    def test_call_validate_deck(self):
        payload = self.rpc(
            "tools/call", {"name": "validate_deck", "arguments": {"deck": minimal_deck()}}
        )["result"]["structuredContent"]
        self.assertTrue(payload["ok"])

    def test_call_build_deck(self):
        response = self.rpc(
            "tools/call", {"name": "build_deck", "arguments": {"deck": minimal_deck()}}
        )["result"]
        self.assertFalse(response["isError"])
        payload = response["structuredContent"]
        self.assertEqual(payload["slides"], 3)
        self.assertTrue(payload["deck_id"])
        self.assertTrue(payload["url"].startswith("http://"))
        self.assertEqual(len(payload["outline"]), 3)

    def test_build_deck_then_read_it_back(self):
        built = self.rpc(
            "tools/call", {"name": "build_deck", "arguments": {"deck": minimal_deck()}}
        )["result"]["structuredContent"]
        deck_id = built["deck_id"]
        read = self.rpc(
            "tools/call", {"name": "read_deck", "arguments": {"deck_id": deck_id}}
        )["result"]["structuredContent"]
        self.assertEqual(read["deck"]["deck"]["title"], "Test deck")

    def test_invalid_deck_returns_paths_and_hints(self):
        response = self.rpc(
            "tools/call",
            {"name": "build_deck", "arguments": {"deck": {"slides": [{"layout": "nope"}]}}},
        )["result"]
        payload = response["structuredContent"]
        self.assertFalse(payload["ok"])
        self.assertIn("slides[0].layout", [e["path"] for e in payload["errors"]])

    def test_unknown_tool_is_reported_not_raised(self):
        response = self.rpc("tools/call", {"name": "nope", "arguments": {}})
        self.assertTrue(response["result"]["isError"])

    def test_tool_call_result_has_text_content(self):
        response = self.rpc(
            "tools/call", {"name": "list_themes", "arguments": {}}
        )["result"]
        content = response["content"]
        self.assertEqual(content[0]["type"], "text")
        json.loads(content[0]["text"])  # the text block is the JSON payload

    def test_list_decks_after_build(self):
        self.rpc("tools/call", {"name": "build_deck", "arguments": {"deck": minimal_deck()}})
        payload = self.rpc(
            "tools/call", {"name": "list_decks", "arguments": {}}
        )["result"]["structuredContent"]
        self.assertEqual(len(payload["decks"]), 1)



class TestMCPProtocol(unittest.TestCase):
    """Malformed input must be a protocol error, not a crash."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = MCPServer(DeckStore(Path(self.tmp.name)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_params_must_be_an_object(self):
        for params in ([], "x", 42):
            response = self.server.handle_message(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": params}
            )
            self.assertEqual(response["error"]["code"], -32602)

    def test_arguments_must_be_an_object(self):
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "list_themes", "arguments": ["nope"]},
            }
        )
        self.assertEqual(response["error"]["code"], -32602)

    def test_missing_tool_name(self):
        response = self.server.handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}}
        )
        self.assertEqual(response["error"]["code"], -32602)

    def test_notification_with_malformed_params_gets_no_response(self):
        self.assertIsNone(
            self.server.handle_message(
                {"jsonrpc": "2.0", "method": "tools/list", "params": []}
            )
        )


if __name__ == "__main__":
    unittest.main()


class TestMCPEdges(unittest.TestCase):
    """The edges a bad client can reach."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = MCPServer(DeckStore(Path(self.tmp.name)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_unsupported_jsonrpc_version_is_an_invalid_request(self):
        """A version other than 2.0 must not raise."""
        response = self.server.handle_message(
            {"jsonrpc": "1.0", "id": 1, "method": "tools/list"}
        )
        self.assertEqual(response["error"]["code"], -32600)

    def test_missing_jsonrpc_field_is_accepted(self):
        response = self.server.handle_message({"id": 1, "method": "tools/list"})
        self.assertIn("tools", response["result"])

    def test_non_string_deck_id_is_a_tool_error(self):
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "build_deck",
                    "arguments": {
                        "deck": {"slides": [{"layout": "closer", "title": "t"}]},
                        "deck_id": ["not", "a", "string"],
                    },
                },
            }
        )
        self.assertTrue(response["result"]["isError"])
        self.assertIn("deck_id", response["result"]["content"][0]["text"])

    def test_non_string_deck_id_on_read_is_a_tool_error(self):
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "read_deck", "arguments": {"deck_id": {"a": 1}}},
            }
        )
        self.assertTrue(response["result"]["isError"])


class TestMCPStdio(unittest.TestCase):
    """The stdio transport must survive a bad frame."""

    def _run(self, frames: list[str]) -> list[dict]:
        import io
        import sys as _sys

        from helmsmate.mcp import stdio_main

        stdin, stdout = _sys.stdin, _sys.stdout
        _sys.stdin = io.StringIO("\n".join(frames) + "\n")
        _sys.stdout = io.StringIO()
        try:
            stdio_main([])
            out = _sys.stdout.getvalue()
        finally:
            _sys.stdin, _sys.stdout = stdin, stdout
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def test_a_non_object_frame_is_rejected_not_fatal(self):
        responses = self._run(
            [
                "[1, 2, 3]",
                "not json at all",
                json.dumps({"jsonrpc": "2.0", "id": 9, "method": "tools/list"}),
            ]
        )
        codes = [r.get("error", {}).get("code") for r in responses]
        self.assertEqual(codes[0], -32600)
        self.assertEqual(codes[1], -32700)
        self.assertIn("tools", responses[2]["result"])

    def test_a_notification_gets_no_frame(self):
        responses = self._run([json.dumps({"jsonrpc": "2.0", "method": "tools/list"})])
        self.assertEqual(responses, [])
