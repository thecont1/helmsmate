"""Validation — the errors an LLM will read and act on."""

from __future__ import annotations

import unittest

import sys
from pathlib import Path

# Direct execution (python tests/test_x.py) needs the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fixtures import REPO, minimal_deck  # noqa: F401

from helmsmate.validate import ERROR, WARNING, is_valid, validate_deck


def paths_for(issues):
    return [i.path for i in issues]


class TestValidate(unittest.TestCase):
    def test_minimal_deck_is_valid(self):
        issues = validate_deck(minimal_deck())
        self.assertEqual([i for i in issues if i.severity == ERROR], [])

    def test_example_deck_is_valid(self):
        import yaml

        with open(REPO / "deck.example.yaml", "r", encoding="utf-8") as f:
            deck = yaml.safe_load(f)
        errors = [i for i in validate_deck(deck) if i.severity == ERROR]
        self.assertEqual(errors, [], f"example deck has errors: {errors}")

    def test_missing_slides(self):
        issues = validate_deck({"deck": {"title": "x"}})
        self.assertIn("slides", paths_for(issues))

    def test_empty_slides(self):
        issues = validate_deck({"slides": []})
        self.assertIn("slides", paths_for(issues))

    def test_unknown_layout_reports_the_layout_name(self):
        deck = minimal_deck(slides=[{"layout": "nope", "title": "x"}])
        issues = validate_deck(deck)
        self.assertIn("slides[0].layout", paths_for(issues))
        self.assertTrue(any("nope" in i.message for i in issues))

    def test_missing_title_is_an_error_with_a_path(self):
        deck = minimal_deck(slides=[{"layout": "closer"}])
        issues = validate_deck(deck)
        self.assertIn("slides[0].title", paths_for(issues))

    def test_unknown_theme(self):
        deck = minimal_deck(theme="does-not-exist")
        issues = validate_deck(deck)
        self.assertIn("theme", paths_for(issues))

    def test_card_heading_is_required(self):
        deck = minimal_deck(
            slides=[
                {
                    "layout": "cards2",
                    "title": "T",
                    "cards": [{"k": "A", "p": "no heading"}, {"h": "ok"}],
                }
            ]
        )
        issues = validate_deck(deck)
        self.assertIn("slides[0].cards[0].h", paths_for(issues))

    def test_unknown_slide_key_is_a_warning_not_an_error(self):
        deck = minimal_deck(slides=[{"layout": "closer", "title": "T", "typo": "value"}])
        issues = validate_deck(deck)
        typo = [i for i in issues if i.path == "slides[0].typo"]
        self.assertEqual(len(typo), 1)
        self.assertEqual(typo[0].severity, WARNING)

    def test_figure2_without_media_is_a_warning(self):
        deck = minimal_deck(slides=[{"layout": "figure2", "title": "T"}])
        issues = validate_deck(deck)
        media = [i for i in issues if i.path == "slides[0].figure"]
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0].severity, WARNING)

    def test_list_valued_note_is_accepted(self):
        """The README shows `note:` as a list — that must validate."""
        deck = minimal_deck(
            slides=[
                {
                    "layout": "cards2",
                    "title": "T",
                    "cards": [{"h": "a"}, {"h": "b"}],
                    "note": ["line one", "line two"],
                }
            ]
        )
        errors = [i for i in validate_deck(deck) if i.severity == ERROR]
        self.assertEqual(errors, [])

    def test_every_error_carries_a_hint(self):
        deck = minimal_deck(slides=[{"layout": "nope"}])
        for issue in validate_deck(deck):
            if issue.severity == ERROR:
                self.assertTrue(issue.hint, f"{issue.path} has no hint")

    def test_is_valid_helper(self):
        self.assertTrue(is_valid(minimal_deck()))
        self.assertFalse(is_valid({"slides": [{"layout": "nope"}]}))

    def test_non_mapping_deck(self):
        issues = validate_deck("not a deck")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, ERROR)


if __name__ == "__main__":
    unittest.main()


class TestLayoutFields(unittest.TestCase):
    """A layout declares the fields it consumes; anything else is ignored."""

    def test_a_field_the_layout_does_not_use_warns(self):
        deck = minimal_deck(slides=[{"layout": "closer", "title": "T", "cards": [{"h": "x"}]}])
        issues = validate_deck(deck)
        warned = [i for i in issues if i.path == "slides[0].cards"]
        self.assertEqual(len(warned), 1)
        self.assertEqual(warned[0].severity, WARNING)

    def test_fields_the_layout_declares_do_not_warn(self):
        deck = minimal_deck(
            slides=[
                {
                    "layout": "figure2",
                    "title": "T",
                    "lede": "x",
                    "lede2": ["a", "b"],
                    "figure": "<svg></svg>",
                }
            ]
        )
        warned = [i for i in validate_deck(deck) if i.severity == WARNING]
        self.assertEqual(warned, [])


class TestBrandMarkValidation(unittest.TestCase):
    def test_a_non_svg_brand_mark_is_an_error(self):
        deck = minimal_deck()
        deck["deck"]["brand"]["mark"] = "assets/mark.png"
        issues = validate_deck(deck)
        self.assertIn("deck.brand.mark", paths_for(issues))
        self.assertTrue(any(i.severity == ERROR for i in issues))

    def test_an_svg_brand_mark_is_accepted(self):
        issues = validate_deck(minimal_deck())
        self.assertNotIn("deck.brand.mark", paths_for(issues))
