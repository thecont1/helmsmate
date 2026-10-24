"""The REST API — over a real socket, so routing and status codes are honest."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from tests.fixtures import REPO, minimal_deck  # noqa: F401

from helmsmate.api import HelmsMateAPI, make_handler
from helmsmate.store import DeckStore


class APITestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DeckStore(Path(self.tmp.name))
        self.api = HelmsMateAPI(self.store, base_url="http://127.0.0.1:8787")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.api, quiet=True))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

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
        self.httpd.shutdown()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.api, token="s3cret"))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.port}"

        status, _ = self.call("GET", "/api/themes")
        self.assertEqual(status, 401)

        status, _ = self.call("GET", "/api/themes", headers={"Authorization": "Bearer s3cret"})
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
