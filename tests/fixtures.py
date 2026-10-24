"""Shared fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


EXAMPLE_DECK = REPO / "deck.example.yaml"


def example_deck() -> dict:
    import yaml

    with open(EXAMPLE_DECK, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def minimal_deck(**overrides) -> dict:
    """A small, valid deck."""
    deck = {
        "deck": {
            "title": "Test deck",
            "brand": {"mark": "assets/sef-corona.svg", "word": "Test **Deck**"},
        },
        "theme": "mariners-chart",
        "slides": [
            {
                "layout": "opener",
                "context": "Opening",
                "eyebrow": "Hello",
                "title": "A test deck.",
                "lede": "Built by the test suite.",
                "stats": [{"big": "3", "small": "slides"}],
            },
            {
                "layout": "cards2",
                "context": "Why",
                "title": "Two cards.",
                "cards": [
                    {"k": "A", "h": "First", "p": "Body"},
                    {"k": "B", "h": "Second", "p": "Body"},
                ],
            },
            {"layout": "closer", "context": "End", "title": "Thanks.", "lede": "Done."},
        ],
    }
    deck.update(overrides)
    return deck
