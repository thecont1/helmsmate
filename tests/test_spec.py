"""The deck contract — schema, catalog, and the invariants between them."""

from __future__ import annotations

import json
import unittest

from tests.fixtures import REPO  # noqa: F401  (path bootstrap)

from helmsmate import spec


class TestSpec(unittest.TestCase):
    def test_every_layout_has_a_schema(self):
        for name in spec.layout_names():
            schema = spec.layout_schema(name)
            self.assertEqual(schema["properties"]["layout"]["const"], name)
            self.assertIn("title", schema["required"])

    def test_catalog_covers_every_layout(self):
        catalog = spec.layout_catalog()
        self.assertEqual(len(catalog), len(spec.LAYOUTS))
        self.assertEqual({c["layout"] for c in catalog}, set(spec.LAYOUTS))

    def test_catalog_entries_are_actionable(self):
        for entry in spec.layout_catalog():
            self.assertTrue(entry["summary"])
            self.assertTrue(entry["example_yaml"])
            self.assertIn("fields", entry)

    def test_deck_schema_is_json_serialisable(self):
        json.dumps(spec.deck_json_schema())

    def test_inline_schema_has_no_dangling_refs(self):
        """A tool schema embedded in a larger schema must not use $ref."""
        schema = spec.inline_deck_schema()
        self.assertNotIn("$defs", schema)
        blob = json.dumps(schema)
        self.assertNotIn("$ref", blob)

    def test_inline_schema_keeps_the_slide_properties(self):
        schema = spec.inline_deck_schema()
        slide = schema["properties"]["slides"]["items"]
        self.assertIn("layout", slide["properties"])
        self.assertIn("cards", slide["properties"])
        self.assertEqual(slide["properties"]["layout"]["enum"], spec.layout_names())

    def test_schema_document_carries_the_contract(self):
        doc = spec.schema_document()
        for key in ("deck_schema", "layouts", "authoring_notes", "conventions"):
            self.assertIn(key, doc)

    def test_authoring_notes_mention_the_conventions(self):
        notes = " ".join(spec.AUTHORING_NOTES)
        self.assertIn("fold", notes)
        self.assertIn("figure_asset", notes)

    def test_field_kinds_render_distinctly(self):
        text = spec.LAYOUTS["opener"].field_map()
        self.assertEqual(text["title"].kind, spec.RICHTEXT)
        self.assertEqual(text["note"].kind, spec.LINES)
        self.assertEqual(text["stats"].kind, spec.STATS)


if __name__ == "__main__":
    unittest.main()
