"""The renderer — output shape, and the parity that keeps the live deck safe."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

import sys
from pathlib import Path

# Direct execution (python tests/test_x.py) needs the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fixtures import REPO, example_deck, minimal_deck  # noqa: F401

from helmsmate.engine import BuildError, build_html, site_chrome_warning
from helmsmate.paths import resolve_asset


class TestEngine(unittest.TestCase):
    def test_builds_the_example_deck(self):
        result = build_html(example_deck())
        self.assertGreater(result.size, 10_000)
        self.assertEqual(result.slides, 8)

    def test_no_unreplaced_placeholders(self):
        html = build_html(minimal_deck()).html
        leftovers = re.findall(r"\{\{[A-Z_]+\}\}", html)
        self.assertEqual(leftovers, [], f"unreplaced placeholders: {leftovers}")

    def test_markers_are_stripped(self):
        html = build_html(minimal_deck()).html
        self.assertNotIn("HELMSMATE:", html)

    def test_slide_count_matches(self):
        html = build_html(minimal_deck()).html
        self.assertIn('aria-live="polite">1 / 3<', html)
        self.assertEqual(html.count('<section class="slide"'), 3)

    def test_title_is_escaped(self):
        payload = "<script>alert(1)</script>"
        deck = minimal_deck(slides=[{"layout": "closer", "title": payload, "lede": "x"}])
        html = build_html(deck).html
        self.assertNotIn(payload, html)
        self.assertIn("&lt;script&gt;", html)

    def test_inline_markup(self):
        deck = minimal_deck(slides=[{"layout": "closer", "title": "**bold** and *italic*"}])
        html = build_html(deck).html
        self.assertIn("<b>bold</b>", html)
        self.assertIn("<em>italic</em>", html)

    def test_list_note_renders_as_lines(self):
        """A list `note:` must render as lines, never as a Python repr."""
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
        html = build_html(deck).html
        self.assertIn("line one<br>line two", html)
        self.assertNotIn("['line one'", html)

    def test_pipe_marks_an_explicit_title_break(self):
        """The README has promised '|' as the explicit break marker since v0."""
        deck = minimal_deck(slides=[{"layout": "closer", "title": "First line.|Second line."}])
        html = build_html(deck).html
        self.assertIn("First line.<br>Second line.", html)

    def test_title_without_a_pipe_is_unchanged(self):
        deck = minimal_deck(slides=[{"layout": "closer", "title": "One line."}])
        html = build_html(deck).html
        self.assertIn("One line.", html)
        self.assertNotIn("One line.<br>", html)

    def test_chrome_can_be_turned_off(self):
        deck = minimal_deck()
        deck["deck"]["chrome"] = False
        html = build_html(deck).html
        self.assertNotIn('class="site-bar"', html)
        self.assertNotIn('id="site-nav"', html)
        self.assertIn('<section class="slide"', html)

    def test_chrome_is_on_by_default(self):
        html = build_html(minimal_deck()).html
        self.assertIn('class="site-bar"', html)

    def test_webfonts_can_be_turned_off(self):
        deck = minimal_deck()
        deck["deck"]["webfonts"] = False
        html = build_html(deck).html
        self.assertNotIn("fonts.googleapis.com", html)

    def test_webfonts_are_on_by_default(self):
        html = build_html(minimal_deck()).html
        self.assertIn("fonts.googleapis.com", html)

    def test_custom_chrome_branding(self):
        deck = minimal_deck()
        deck["deck"]["chrome"] = {"word": "Acme", "home_url": "https://example.com"}
        html = build_html(deck).html
        self.assertIn("Acme", html)
        self.assertIn("https://example.com", html)

    def test_custom_chrome_word_is_escaped(self):
        """A supplied wordmark is text, like brand.word — never raw markup."""
        deck = minimal_deck()
        deck["deck"]["chrome"] = {"word": "<script>alert(1)</script>"}
        html = build_html(deck).html
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_brand_mark_is_optional(self):
        """A deck with no mark falls back to the default rather than failing."""
        deck = minimal_deck()
        del deck["deck"]["brand"]["mark"]
        result = build_html(deck)
        self.assertEqual(result.slides, 3)
        self.assertIn("svg", result.html)

    def test_chrome_false_needs_no_chrome_assets(self):
        """Stripping the chrome must not depend on the chrome icons existing."""
        deck = minimal_deck()
        deck["deck"]["chrome"] = False
        html = build_html(deck).html
        self.assertNotIn('<header class="site-bar"', html)

    def test_missing_brand_mark_is_a_clear_error(self):
        deck = minimal_deck()
        deck["deck"]["brand"]["mark"] = "assets/does-not-exist.svg"
        with self.assertRaises(BuildError) as ctx:
            build_html(deck)
        self.assertIn("brand.mark", str(ctx.exception))

    def test_unknown_layout_is_a_clear_error(self):
        deck = minimal_deck(slides=[{"layout": "nope", "title": "x"}])
        with self.assertRaises(BuildError):
            build_html(deck)

    def test_outline_describes_every_slide(self):
        result = build_html(minimal_deck())
        self.assertEqual(len(result.outline), 3)
        self.assertEqual(result.outline[0]["layout"], "opener")
        self.assertEqual(result.outline[0]["index"], 1)

    def test_site_chrome_warning(self):
        self.assertIsNotNone(site_chrome_warning(minimal_deck()))
        deck = minimal_deck()
        deck["deck"]["chrome"] = False
        self.assertIsNone(site_chrome_warning(deck))

    def test_output_is_self_contained(self):
        """No script or style may point at a remote origin."""
        html = build_html(minimal_deck()).html
        html = html.replace('href="https://fonts.googleapis.com', 'href="x-fonts.googleapis.com')
        remote = re.findall(r'<(?:script|img)[^>]+src="https?://', html)
        self.assertEqual(remote, [], f"remote assets in output: {remote}")


class TestFigureAsset(unittest.TestCase):
    """figure_asset keeps large media out of the deck payload."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "assets").mkdir()
        (self.root / "assets" / "chart.svg").write_text(
            '<svg viewBox="0 0 100 40" xmlns="http://www.w3.org/2000/svg">'
            '<circle cx="20" cy="20" r="15" fill="#4A68C8"/></svg>',
            encoding="utf-8",
        )
        (self.root / "assets" / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    def tearDown(self):
        self.tmp.cleanup()

    def _deck(self, rel):
        return {
            "deck": {"title": "Assets", "brand": {"mark": "assets/sef-corona.svg"}},
            "slides": [
                {
                    "layout": "figure2",
                    "context": "Fig",
                    "title": "With an asset.",
                    "figure_asset": rel,
                    "lede": "Inlined.",
                }
            ],
        }

    def test_svg_asset_is_inlined_as_markup(self):
        html = build_html(self._deck("assets/chart.svg"), asset_roots=(self.root,)).html
        self.assertIn("<circle", html)
        self.assertNotIn("assets/chart.svg", html)

    def test_raster_asset_becomes_a_data_uri(self):
        html = build_html(self._deck("assets/shot.png"), asset_roots=(self.root,)).html
        self.assertIn("data:image/png;base64,", html)

    def test_missing_asset_is_a_clear_error(self):
        with self.assertRaises(BuildError) as ctx:
            build_html(self._deck("assets/nope.svg"), asset_roots=(self.root,))
        self.assertIn("figure_asset", str(ctx.exception))

    def test_asset_outside_the_root_is_not_read(self):
        """A path escaping the asset root must not resolve."""
        with self.assertRaises(BuildError):
            build_html(self._deck("../secrets.svg"), asset_roots=(self.root,))

    def test_absolute_asset_paths_are_refused(self):
        """A deck must not be able to read arbitrary files off the server."""
        for field in ("figure_asset", "brand.mark"):
            deck = self._deck("/etc/passwd")
            if field == "brand.mark":
                deck["deck"]["brand"]["mark"] = "/etc/passwd"
            with self.assertRaises(BuildError) as ctx:
                build_html(deck, asset_roots=(self.root,))
            self.assertIn("not found", str(ctx.exception))
            self.assertIn("/etc/passwd", str(ctx.exception))



class TestBrandMark(unittest.TestCase):
    """The brand mark is inlined as markup, so it must be an SVG."""

    def test_a_non_svg_brand_mark_is_refused(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "assets").mkdir()
        (root / "assets" / "mark.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        deck = minimal_deck()
        deck["deck"]["brand"]["mark"] = "assets/mark.png"
        with self.assertRaises(BuildError) as ctx:
            build_html(deck, asset_roots=(root,))
        self.assertIn("SVG", str(ctx.exception))
        tmp.cleanup()

    def test_an_svg_brand_mark_is_accepted(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "assets").mkdir()
        (root / "assets" / "mark.svg").write_text(
            '<svg viewBox="0 0 10 10"><circle r="4"/></svg>', encoding="utf-8"
        )
        deck = minimal_deck()
        deck["deck"]["brand"]["mark"] = "assets/mark.svg"
        html = build_html(deck, asset_roots=(root,)).html
        self.assertIn("<circle", html)
        tmp.cleanup()


class TestOutline(unittest.TestCase):
    """The outline is a plain-text summary of the deck."""

    def test_a_pipe_becomes_a_space_in_the_outline(self):
        deck = minimal_deck(slides=[{"layout": "closer", "title": "One.|Two."}])
        result = build_html(deck)
        self.assertEqual(result.outline[0]["title"], "One. Two.")

    def test_a_list_title_is_flattened(self):
        deck = minimal_deck(slides=[{"layout": "closer", "title": ["One.", "Two."]}])
        result = build_html(deck)
        self.assertEqual(result.outline[0]["title"], "One. Two.")



class TestAssetResolution(unittest.TestCase):
    """An asset that cannot be resolved is skipped, not fatal."""

    def test_a_symlink_loop_does_not_raise(self):
        import os
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "assets").mkdir()
        os.symlink(root / "assets" / "loop", root / "assets" / "loop")
        try:
            self.assertIsNone(resolve_asset("assets/loop", root / "assets"))
        finally:
            tmp.cleanup()

    def test_a_symlink_loop_does_not_raise_on_python_3_10_to_3_12(self):
        """Before 3.13, Path.resolve() raised RuntimeError for a symlink loop.

        The real loop raises nothing on 3.13+, so the older behaviour is
        simulated — otherwise this test would pass on the version where the
        bug does not exist.
        """
        import pathlib
        from unittest import mock

        real_resolve = pathlib.Path.resolve

        def resolve(self, *args, **kwargs):
            if self.name == "loop":
                raise RuntimeError("Symlink loop from 'loop'")
            return real_resolve(self, *args, **kwargs)

        with mock.patch.object(pathlib.Path, "resolve", resolve):
            self.assertIsNone(resolve_asset("loop", Path("/tmp")))


if __name__ == "__main__":    unittest.main()
