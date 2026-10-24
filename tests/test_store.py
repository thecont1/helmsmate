"""The store — decks need identity before they can be edited."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import REPO  # noqa: F401

from helmsmate.store import DeckStore, StoreError, make_id, slugify


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DeckStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def _deck(self, title="Test deck"):
        return {
            "deck": {"title": title, "brand": {"mark": "assets/sef-corona.svg"}},
            "theme": "mariners-chart",
            "slides": [{"layout": "closer", "title": "Hello"}],
        }

    def test_save_and_read_round_trip(self):
        deck = self._deck()
        record = self.store.save(deck, "<html>built</html>")
        self.assertEqual(record.slides, 1)
        self.assertEqual(record.title, "Test deck")
        self.assertEqual(self.store.read_deck(record.id)["deck"]["title"], "Test deck")
        self.assertEqual(self.store.read_html(record.id), "<html>built</html>")

    def test_source_survives_the_round_trip(self):
        deck = self._deck("Round trip")
        record = self.store.save(deck, "x")
        self.assertIn("Round trip", self.store.read_yaml(record.id))

    def test_list_returns_the_deck(self):
        record = self.store.save(self._deck(), "x")
        ids = [r.id for r in self.store.list()]
        self.assertIn(record.id, ids)

    def test_missing_deck_raises(self):
        with self.assertRaises(StoreError):
            self.store.get("nope")
        with self.assertRaises(StoreError):
            self.store.read_deck("nope")

    def test_delete_removes_the_deck(self):
        record = self.store.save(self._deck(), "x")
        self.assertTrue(self.store.delete(record.id))
        self.assertFalse(self.store.delete(record.id))
        self.assertEqual(self.store.list(), [])

    def test_deck_id_is_filesystem_safe(self):
        record = self.store.save(self._deck("../../escape"), "x")
        self.assertNotIn("/", record.id)
        self.assertNotIn("..", record.id)

    def test_deck_id_cannot_climb_out_of_the_workspace(self):
        """'..' must never reach the filesystem — delete() would rmtree it."""
        for bad in ("..", ".", "../..", "a/b", "..hidden", "/etc"):
            with self.assertRaises(StoreError):
                self.store.deck_dir(bad)

    def test_delete_refuses_to_climb_out(self):
        parent = Path(self.tmp.name) / "parent"
        parent.mkdir()
        sentinel = parent / "keep.txt"
        sentinel.write_text("keep me", encoding="utf-8")
        store = DeckStore(parent / "workspace")
        store.workspace.mkdir()
        with self.assertRaises(StoreError):
            store.delete("..")
        self.assertTrue(sentinel.exists())

    def test_explicit_deck_id_is_honoured(self):
        record = self.store.save(self._deck(), "x", deck_id="my-deck")
        self.assertEqual(record.id, "my-deck")

    def test_slugify(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")
        self.assertEqual(slugify(""), "deck")

    def test_make_id_is_stable_for_the_same_input(self):
        self.assertEqual(make_id("Title", "salt"), make_id("Title", "salt"))
        self.assertNotEqual(make_id("Title", "a"), make_id("Title", "b"))

    def test_asset_roots_include_the_repository(self):
        roots = self.store.asset_roots()
        self.assertTrue(any((r / "assets" / "sef-corona.svg").exists() for r in roots))


if __name__ == "__main__":
    unittest.main()
