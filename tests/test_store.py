"""The store — decks need identity before they can be edited."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys
from pathlib import Path

# Direct execution (python tests/test_x.py) needs the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

    def test_asset_roots_are_asset_directories(self):
        """Roots are asset directories — a deck may reach an image, not a tree."""
        roots = self.store.asset_roots()
        self.assertTrue(any((r / "sef-corona.svg").exists() for r in roots))
        for root in roots:
            self.assertEqual(root.name, "assets")



class TestStoreIdentity(unittest.TestCase):
    """Implicit ids, and writes that never leave a deck half-written."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DeckStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def _deck(self, title="Same title", marker="A"):
        return {
            "deck": {"title": title},
            "slides": [{"layout": "closer", "title": marker}],
        }

    def test_the_same_deck_rebuilds_in_place(self):
        first = self.store.save(self._deck(), "<html>1</html>")
        second = self.store.save(self._deck(), "<html>2</html>")
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.store.read_html(first.id), "<html>2</html>")

    def test_different_decks_with_the_same_title_do_not_collide(self):
        first = self.store.save(self._deck(marker="A"), "<html>A</html>")
        second = self.store.save(self._deck(marker="B"), "<html>B</html>")
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(self.store.list()), 2)
        self.assertEqual(self.store.read_html(first.id), "<html>A</html>")

    def test_an_explicit_id_still_updates(self):
        self.store.save(self._deck(), "<html>1</html>", deck_id="fixed")
        again = self.store.save(self._deck(marker="B"), "<html>2</html>", deck_id="fixed")
        self.assertEqual(again.id, "fixed")
        self.assertEqual(len(self.store.list()), 1)

    def test_a_failed_write_leaves_the_stored_deck_unchanged(self):
        record = self.store.save(self._deck(), "<html>good</html>")

        class Unserialisable:
            pass

        broken = {"deck": {"title": "Broken"}, "slides": [Unserialisable()]}
        with self.assertRaises(Exception):
            self.store.save(broken, "<html>bad</html>", deck_id=record.id)

        # The old deck is intact — no half-written source, no stray staging.
        self.assertEqual(self.store.read_html(record.id), "<html>good</html>")
        self.assertEqual(self.store.read_deck(record.id)["slides"][0]["title"], "A")
        leftovers = [p.name for p in self.store.workspace.iterdir() if p.name.startswith(".")]
        self.assertEqual(leftovers, [])



class TestStoreConcurrency(unittest.TestCase):
    """Two builds of the same deck must not collide."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DeckStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_concurrent_saves_of_one_deck(self):
        import threading

        deck = {"deck": {"title": "Race"}, "slides": [{"layout": "closer", "title": "x"}]}
        errors: list[str] = []

        def worker(n: int) -> None:
            try:
                self.store.save(deck, f"<html>{n}</html>", deck_id="raced")
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(
            sorted(p.name for p in self.store.deck_dir("raced").iterdir()),
            ["deck.yaml", "index.html", "meta.json"],
        )
        stray = [p.name for p in self.store.workspace.iterdir() if p.name.startswith(".")]
        self.assertEqual(stray, [], "staging or backup directories left behind")


if __name__ == "__main__":
    unittest.main()
