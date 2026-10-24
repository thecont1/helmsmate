"""Deck store — built decks on disk, with identity.

Every built deck gets a directory::

    <workspace>/<deck-id>/
        deck.yaml     # the authored source
        index.html    # the built presentation
        meta.json     # title, slide count, timestamps, theme

The workspace defaults to ``<repo>/decks`` and can be moved with
``HELMSMATE_WORKSPACE`` or the ``--workspace`` flag. It is deliberately
separate from the repository: decks are build products, not source.

The store is also the seam for phase two. ``read_deck`` hands back the
authored structure, so an edit can be applied to the source and rebuilt —
rather than trying to patch generated HTML.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import paths

SLUG_MAX = 48


class StoreError(Exception):
    """Raised when a deck cannot be stored or fetched."""


@dataclass
class DeckRecord:
    """Metadata about one stored deck."""

    id: str
    title: str
    slides: int
    theme: str
    bytes: int
    created_at: str
    updated_at: str
    path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:SLUG_MAX].strip("-") or "deck"


def make_id(title: str, salt: str = "") -> str:
    """Stable-ish, filesystem-safe id: slug plus a short content hash."""
    digest = hashlib.sha256((title + "|" + salt).encode("utf-8")).hexdigest()[:6]
    return f"{slugify(title)}-{digest}"


def content_digest(deck: dict) -> str:
    """A digest of the deck's content.

    The implicit id is derived from this, so building the same deck twice
    updates one deck, while two different decks that happen to share a title
    get their own ids instead of overwriting each other.
    """
    canonical = yaml.safe_dump(deck, sort_keys=True, allow_unicode=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


class DeckStore:
    """Filesystem-backed deck storage."""

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = Path(workspace) if workspace else paths.default_workspace()
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, deck_id: str) -> threading.Lock:
        """A lock per deck id.

        The API server is threaded, and two clients can build the same deck
        at the same time — an implicit id is derived from the content, so
        the same deck really can collide. One save at a time per deck.
        """
        with self._locks_guard:
            lock = self._locks.get(deck_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[deck_id] = lock
            return lock

    # ── paths ──────────────────────────────────────────────────────────────

    @property
    def assets_root(self) -> Path:
        """Where ``figure_asset`` paths are resolved from."""
        return self.workspace / "assets"

    def asset_roots(self) -> tuple[Path, ...]:
        """Search path for assets, in priority order.

        Workspace assets win, then the repository's built-in assets (the
        brand mark and chrome icons), so a deck can use the shipped artwork
        without copying it in. Both roots are asset directories — a deck may
        reach an image, not every file in the tree.
        """
        return (self.assets_root, paths.assets_dir())

    def deck_dir(self, deck_id: str) -> Path:
        """The directory for a deck id — rejecting anything that escapes.

        The id must start with an alphanumeric character, which rules out
        ``.`` and ``..``; and the resolved path must sit inside the
        workspace, which rules out anything else that might climb out.
        """
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", deck_id or ""):
            raise StoreError(f"Invalid deck id: {deck_id!r}")
        target = (self.workspace / deck_id).resolve()
        try:
            target.relative_to(self.workspace.resolve())
        except ValueError as exc:
            raise StoreError(f"Invalid deck id: {deck_id!r}") from exc
        return target

    # ── writes ─────────────────────────────────────────────────────────────

    def save(self, deck: dict, html: str, deck_id: str | None = None) -> DeckRecord:
        """Write the source and the built HTML, returning the record.

        The files are written to a temporary directory and swapped into
        place, so a failure part-way through leaves the stored deck as it
        was rather than half-written.
        """
        title = str((deck.get("deck", {}) or {}).get("title") or "Untitled deck")
        slides = len(deck.get("slides", []) or [])
        theme = str(deck.get("theme") or "")
        deck_id = deck_id or make_id(title, content_digest(deck))

        target = self.deck_dir(deck_id)
        target.parent.mkdir(parents=True, exist_ok=True)

        created = _now()
        existing_meta = target / "meta.json"
        if existing_meta.exists():
            try:
                created = json.loads(existing_meta.read_text(encoding="utf-8")).get("created_at", created)
            except (json.JSONDecodeError, OSError):
                pass

        record = DeckRecord(
            id=deck_id,
            title=title,
            slides=slides,
            theme=theme,
            bytes=len(html.encode("utf-8")),
            created_at=created,
            updated_at=_now(),
            path=str(target),
        )

        with self._lock_for(deck_id):
            # A unique staging directory per save: two builds of the same
            # deck must not share a path.
            staging = Path(
                tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=str(target.parent))
            )
            try:
                with open(staging / "deck.yaml", "w", encoding="utf-8") as f:
                    yaml.safe_dump(deck, f, sort_keys=False, allow_unicode=True, width=100)
                with open(staging / "index.html", "w", encoding="utf-8") as f:
                    f.write(html)
                (staging / "meta.json").write_text(
                    json.dumps(record.to_dict(), indent=2), encoding="utf-8"
                )
                self._swap(staging, target)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        return record

    @staticmethod
    def _swap(staging: Path, target: Path) -> None:
        """Move a staged deck into place, keeping the old one if it fails."""
        # A unique path that does not exist yet, for the old deck to move to.
        backup = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.previous-", dir=str(target.parent))
        )
        backup.rmdir()
        if target.exists():
            target.rename(backup)
        try:
            staging.rename(target)
        except OSError:
            if backup.exists():
                backup.rename(target)  # put the old deck back
            raise
        shutil.rmtree(backup, ignore_errors=True)

    # ── reads ──────────────────────────────────────────────────────────────

    def get(self, deck_id: str) -> DeckRecord:
        meta_path = self.deck_dir(deck_id) / "meta.json"
        if not meta_path.exists():
            raise StoreError(f"No such deck: {deck_id}")
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise StoreError(f"Corrupt deck metadata: {deck_id}") from exc
        try:
            return DeckRecord(**data)
        except TypeError as exc:
            raise StoreError(f"Corrupt deck metadata: {deck_id}") from exc

    def read_deck(self, deck_id: str) -> dict:
        """The authored deck, as a dict — the seam phase-two editing works on."""
        source = self.deck_dir(deck_id) / "deck.yaml"
        if not source.exists():
            raise StoreError(f"No such deck: {deck_id}")
        with open(source, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def read_yaml(self, deck_id: str) -> str:
        source = self.deck_dir(deck_id) / "deck.yaml"
        if not source.exists():
            raise StoreError(f"No such deck: {deck_id}")
        return source.read_text(encoding="utf-8")

    def read_html(self, deck_id: str) -> str:
        built = self.deck_dir(deck_id) / "index.html"
        if not built.exists():
            raise StoreError(f"No such deck: {deck_id}")
        return built.read_text(encoding="utf-8")

    def list(self) -> list[DeckRecord]:
        """Every stored deck, newest first."""
        records: list[DeckRecord] = []
        if not self.workspace.exists():
            return records
        for child in sorted(self.workspace.iterdir()):
            if not child.is_dir() or not (child / "meta.json").exists():
                continue
            try:
                records.append(self.get(child.name))
            except StoreError:
                continue
        records.sort(key=lambda r: r.updated_at, reverse=True)
        return records

    def delete(self, deck_id: str) -> bool:
        target = self.deck_dir(deck_id)
        if not target.exists():
            return False
        shutil.rmtree(target)
        return True
