"""Filesystem layout for HelmsMate.

The engine, themes, template and assets live in the repository. The API adds a
*workspace* — a writable directory where built decks are stored. Both are
resolved here so the rest of the package never guesses a path.
"""

from __future__ import annotations

import os
from pathlib import Path

# Repository root — the parent of the `helmsmate` package.
REPO_ROOT = Path(__file__).resolve().parent.parent

TEMPLATE_FILE = REPO_ROOT / "engine" / "template.html"
THEMES_DIR = REPO_ROOT / "themes"
ASSETS_DIR = REPO_ROOT / "assets"
DIST_DIR = REPO_ROOT / "dist"


def repo_root() -> Path:
    """Root of the HelmsMate data: template, themes and built-in assets.

    Three layouts, in order:
      1. ``HELMSMATE_ROOT`` — explicit override.
      2. An installed package (``helmsmate/_data/``).
      3. A checkout — the repository this package lives in.
    """
    env = os.environ.get("HELMSMATE_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    packaged = Path(__file__).resolve().parent / "_data"
    if (packaged / "template.html").exists():
        return packaged
    checkout = Path(__file__).resolve().parent.parent
    if (checkout / "engine" / "template.html").exists():
        return checkout
    return REPO_ROOT


def template_file() -> Path:
    root = repo_root()
    for candidate in (root / "engine" / "template.html", root / "template.html"):
        if candidate.exists():
            return candidate
    return root / "engine" / "template.html"


def themes_dir() -> Path:
    root = repo_root()
    for candidate in (root / "themes", root / "_data" / "themes"):
        if candidate.exists():
            return candidate
    return root / "themes"


def assets_dir() -> Path:
    root = repo_root()
    for candidate in (root / "assets", root / "_data" / "assets"):
        if candidate.exists():
            return candidate
    return root / "assets"


def default_workspace() -> Path:
    """Where built decks are stored. Override with HELMSMATE_WORKSPACE.

    In a checkout this is ``<repo>/decks``. An installed package writes to
    the user's data directory instead — site-packages is not ours to write
    into, and may not even be writable.
    """
    env = os.environ.get("HELMSMATE_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    root = repo_root()
    if (root / "engine" / "template.html").exists():
        return root / "decks"
    return user_data_dir()


def user_data_dir() -> Path:
    """A per-user, writable directory for HelmsMate's data."""
    env = os.environ.get("XDG_DATA_HOME")
    base = Path(env).expanduser() if env else Path.home() / ".local" / "share"
    return base / "helmsmate" / "decks"


def resolve_asset(rel: str, *roots: Path) -> Path | None:
    """Resolve an asset path against a list of roots.

    Only relative paths are accepted, and only ones that stay inside a root.
    A deck must not be able to read arbitrary files off the server — assets
    live in the workspace, and that is where they come from.
    """
    rel = (rel or "").strip()
    if not rel:
        return None
    if Path(rel).is_absolute():
        return None
    # A root is an asset directory, so 'assets/chart.svg' and 'chart.svg'
    # should both find the file. Try the path as given, then without the
    # 'assets/' prefix.
    variants = [rel]
    if rel.startswith("assets/"):
        variants.append(rel[len("assets/") :])
    for root in roots:
        if not root:
            continue
        for variant in variants:
            try:
                target = (root / variant).resolve()
                target.relative_to(root.resolve())
                if target.exists():
                    return target
            except (OSError, ValueError):
                # A symlink loop, a permission problem, or a path that
                # escapes this root — try the next variant.
                continue
    return None
