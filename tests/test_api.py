"""The REST API — over a real socket, so routing and status codes are honest."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import sys
from pathlib import Path

# Direct execution (python tests/test_x.py) needs the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fixtures import REPO, minimal_deck  # noqa: F401

from helmsmate.api import HelmsMateAPI, HelmsMateServer, make_handler
from helmsmate.store import DeckStore


class APITestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DeckStore(Path(self.tmp.name))
        self.api = HelmsMateAPI(self.store, base_url="http://127.0.0.1:8787")
        self.httpd = HelmsMateServer(("127.0.0.1", 0), make_handler(self.api, quiet=True))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def _restart_with(self, **kwargs):
        """Swap in a server with different options, closing the old one."""
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd = HelmsMateServer(("127.0.0.1", 0), make_handler(self.api, quiet=True, **kwargs))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.port}"

    def call(self, method, path, body=None, headers=None):
        data = None
        head = {"Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        if headers:
            head.update(headers)
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=head)
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


class TestDiscovery(APITestCase):
    def test_index(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("/api/schema", body["discovery"]["deck_schema"])

    def test_openapi_document(self):
        status, body = self.call("GET", "/openapi.json")
        self.assertEqual(status, 200)
        self.assertEqual(body["openapi"], "3.1.0")
        self.assertIn("/api/decks", body["paths"])
        self.assertIn("Deck", body["components"]["schemas"])

    def test_schema_endpoint(self):
        status, body = self.call("GET", "/api/schema")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["layouts"]), 6)

    def test_layouts_listing(self):
        status, body = self.call("GET", "/api/layouts")
        self.assertEqual(status, 200)
        self.assertIn("opener", [x["layout"] for x in body["layouts"]])

    def test_single_layout(self):
        status, body = self.call("GET", "/api/layouts/cards2")
        self.assertEqual(status, 200)
        self.assertEqual(body["layout"]["layout"], "cards2")
        self.assertIn("cards", body["schema"]["properties"])

    def test_unknown_layout_is_404(self):
        status, _ = self.call("GET", "/api/layouts/nope")
        self.assertEqual(status, 404)

    def test_themes(self):
        status, body = self.call("GET", "/api/themes")
        self.assertEqual(status, 200)
        self.assertIn("mariners-chart", [t["name"] for t in body["themes"]])

    def test_unknown_route_is_404(self):
        status, _ = self.call("GET", "/nope")
        self.assertEqual(status, 404)

    def test_wrong_method_is_405(self):
        status, _ = self.call("GET", "/api/decks/validate")
        self.assertEqual(status, 405)


class TestDecks(APITestCase):
    def test_build_returns_a_viewable_deck(self):
        status, body = self.call("POST", "/api/decks", {"deck": minimal_deck()})
        self.assertEqual(status, 201)
        self.assertEqual(body["slides"], 3)
        self.assertIn("deck_id", body)
        self.assertTrue(body["url"].endswith(body["deck_id"] + "/"))

        deck_id = body["deck_id"]
        self.assertEqual(self.call("GET", f"/api/decks/{deck_id}")[0], 200)
        self.assertEqual(self.call("GET", f"/api/decks/{deck_id}/yaml")[0], 200)
        self.assertEqual(self.call("GET", f"/api/decks/{deck_id}/html")[0], 200)
        self.assertEqual(self.call("GET", f"/decks/{deck_id}/")[0], 200)

    def test_built_html_is_a_presentation(self):
        _, body = self.call("POST", "/api/decks", {"deck": minimal_deck()})
        status, html = self.call("GET", f"/api/decks/{body['deck_id']}/html")
        self.assertEqual(status, 200)
        self.assertIn("<section class=\"slide\"", html)
        self.assertIn("A test deck.", html)

    def test_list_decks(self):
        self.call("POST", "/api/decks", {"deck": minimal_deck()})
        status, body = self.call("GET", "/api/decks")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["decks"]), 1)

    def test_invalid_deck_is_422_with_paths(self):
        deck = {"slides": [{"layout": "nope", "title": "x"}]}
        status, body = self.call("POST", "/api/decks", {"deck": deck})
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "invalid_deck")
        self.assertIn("slides[0].layout", [d["path"] for d in body["error"]["details"]])

    def test_validate_endpoint(self):
        status, body = self.call("POST", "/api/decks/validate", {"deck": minimal_deck()})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_validate_endpoint_reports_errors(self):
        status, body = self.call(
            "POST", "/api/decks/validate", {"deck": {"slides": [{"layout": "closer"}]}}
        )
        self.assertEqual(status, 200)
        self.assertFalse(body["ok"])
        self.assertTrue(body["errors"])

    def test_bare_deck_object_is_accepted(self):
        status, _ = self.call("POST", "/api/decks", minimal_deck())
        self.assertEqual(status, 201)

    def test_yaml_body_is_accepted(self):
        import yaml

        raw = yaml.safe_dump(minimal_deck()).encode("utf-8")
        req = urllib.request.Request(
            self.base + "/api/decks",
            data=raw,
            method="POST",
            headers={"Content-Type": "text/yaml"},
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)

    def test_delete_deck(self):
        _, body = self.call("POST", "/api/decks", {"deck": minimal_deck()})
        deck_id = body["deck_id"]
        self.assertEqual(self.call("DELETE", f"/api/decks/{deck_id}")[0], 200)
        self.assertEqual(self.call("GET", f"/api/decks/{deck_id}")[0], 404)

    def test_unknown_deck_is_404(self):
        self.assertEqual(self.call("GET", "/api/decks/nope")[0], 404)


class TestAuth(APITestCase):
    def test_token_required(self):
        self._restart_with(token="s3cret")

        status, _ = self.call("GET", "/api/themes")
        self.assertEqual(status, 401)

        status, _ = self.call("GET", "/api/themes", headers={"Authorization": "Bearer s3cret"})
        self.assertEqual(status, 200)



class TestServiceBehaviour(APITestCase):
    """The service surface: error envelopes, CORS, headers."""

    def test_invalid_deck_id_is_a_client_error_not_a_500(self):
        status, body = self.call("POST", "/api/decks", {"deck": minimal_deck(), "deck_id": ".."})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_deck_id")

    def test_delete_with_a_bad_id_is_a_client_error(self):
        status, body = self.call("DELETE", "/api/decks/..")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_deck_id")

    def test_delete_of_a_missing_deck_is_404(self):
        status, _ = self.call("DELETE", "/api/decks/nope")
        self.assertEqual(status, 404)

    def test_cors_is_off_by_default(self):
        """A local service must not answer '*' to every page in the browser."""
        req = urllib.request.Request(self.base + "/api/themes")
        with urllib.request.urlopen(req) as resp:
            self.assertIsNone(resp.headers.get("Access-Control-Allow-Origin"))

    def test_head_is_supported(self):
        req = urllib.request.Request(self.base + "/api/themes", method="HEAD")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)

    def test_malformed_content_length_is_a_bad_request(self):
        req = urllib.request.Request(
            self.base + "/api/decks", data=b"{}", method="POST",
            headers={"Content-Type": "application/json", "Content-Length": "abc"},
        )
        try:
            urllib.request.urlopen(req)
            self.fail("expected a 400")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)

    def test_mcp_params_must_be_an_object(self):
        status, body = self.call(
            "POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": []}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["error"]["code"], -32602)


class TestTransportBehaviour(APITestCase):
    """The HTTP layer: framing, tokens, and headers."""

    def _raw(self, request_bytes: bytes, read: int = 4096) -> bytes:
        import socket

        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(request_bytes)
            sock.settimeout(2)
            try:
                return sock.recv(read)
            except socket.timeout:
                return b""

    def test_401_does_not_desync_the_connection(self):
        """The body must be drained, or the next request reads the leftovers."""
        self._restart_with(token="tok")

        body = b'{"deck": {"slides": []}}'
        raw = self._raw(
            b"POST /mcp HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        self.assertIn(b"401", raw.split(b"\r\n")[0])

        # A second request on a fresh connection must be understood.
        raw2 = self._raw(
            b"GET /api/themes HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer tok\r\n\r\n"
        )
        self.assertIn(b"200 OK", raw2.split(b"\r\n")[0])

    def test_non_ascii_token_does_not_crash(self):
        self._restart_with(token="clé")

        status, _ = self.call("GET", "/api/themes")
        self.assertEqual(status, 401)
        status, _ = self.call("GET", "/api/themes", headers={"Authorization": "Bearer clé"})
        self.assertEqual(status, 200)

    def test_bearer_scheme_is_case_insensitive(self):
        self._restart_with(token="tok")

        status, _ = self.call("GET", "/api/themes", headers={"Authorization": "bearer tok"})
        self.assertEqual(status, 200)

    def test_an_empty_token_is_refused(self):
        with self.assertRaises(ValueError):
            make_handler(self.api, token="")

    def test_chunked_bodies_are_refused(self):
        status, body = self.call_raw_chunked()
        self.assertEqual(status, 411)

    def test_201_points_at_the_new_deck(self):
        req = urllib.request.Request(
            self.base + "/api/decks",
            data=json.dumps({"deck": minimal_deck()}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            self.assertTrue(resp.headers.get("Location", "").startswith("/api/decks/"))

    def test_bare_deck_with_a_deck_id_is_accepted(self):
        deck = minimal_deck()
        deck["deck_id"] = "my-deck"
        status, body = self.call("POST", "/api/decks", deck)
        self.assertEqual(status, 201)
        self.assertEqual(body["deck_id"], "my-deck")

    def call_raw_chunked(self):
        import socket

        raw = (
            b"POST /api/decks HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n\r\n"
        )
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(raw)
            sock.settimeout(3)
            data = b""
            try:
                while b"\r\n\r\n" not in data:
                    chunk = sock.recv(1024)
                    if not chunk:
                        break
                    data += chunk
            except socket.timeout:
                pass
        head = data.split(b"\r\n")[0].decode(errors="replace")
        status = int(head.split()[1]) if len(head.split()) > 1 else 0
        return status, data


class TestHeaders(APITestCase):
    """What the server sends back."""

    def test_nosniff_on_every_response(self):
        import urllib.request

        with urllib.request.urlopen(self.base + "/api/themes") as resp:
            self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")

    def test_served_decks_carry_a_csp_that_blocks_outbound_calls(self):
        _, body = self.call("POST", "/api/decks", {"deck": minimal_deck()})
        deck_id = body["deck_id"]

        req = urllib.request.Request(self.base + f"/decks/{deck_id}/")
        with urllib.request.urlopen(req) as resp:
            csp = resp.headers.get("Content-Security-Policy", "")
        self.assertIn("connect-src 'none'", csp)
        self.assertIn("default-src 'self'", csp)


if __name__ == "__main__":
    unittest.main()
