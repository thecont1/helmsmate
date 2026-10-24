"""Theme registry — named themes, and the CSS custom properties they emit.

A theme lives in ``themes/<name>.theme.yaml``::

    name: Mariner's Chart
    colors: {paper: "#FBFBFD", beacon: {500: "#4A68C8"}}
    fonts:  {display: "...", sans: "...", mono: "..."}
    effects: {grid_glow: "rgba(...)"}
    dark:   {...}   # optional second colour mode

Nested keys flatten to CSS custom properties: ``colors.beacon.500`` becomes
``--beacon-500``, ``fonts.display`` becomes ``--font-display``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import paths

THEME_SUFFIX = ".theme.yaml"
DEFAULT_THEME = "mariners-chart"


def _flat_vars(node: dict, base_path: list[str] | None = None) -> list[tuple[str, Any]]:
    """Walk a theme sub-tree; return (var_name, value) tuples.

    ``colors`` and ``effects`` are dropped from the CSS-var path, so
    ``colors.beacon.50`` becomes ``--beacon-50``. Underscores in keys are
    normalised to dashes (``grid_glow`` → ``--grid-glow``).
    """
    if base_path is None:
        base_path = []
    out: list[tuple[str, Any]] = []
    for k, v in node.items():
        if base_path == [] and k == "name":
            continue
        path = base_path + [k]
        if isinstance(v, dict):
            out.extend(_flat_vars(v, path))
        else:
            parts = [p for p in path if p not in ("colors", "effects")]
            if parts and parts[0] == "fonts":
                parts[0] = "font"
            var = "-".join(str(p) for p in parts).replace("_", "-")
            out.append((var, v))
    return out


def css_vars_from_theme(theme: dict) -> str:
    """Flatten a theme into CSS custom properties for one or two colour modes.

    If the theme has a top-level ``dark`` key, those values are emitted inside
    a ``@media (prefers-color-scheme: dark)`` block *and* a
    ``:root[data-theme="dark"]`` block, so the deck's theme toggle works
    regardless of the OS preference.
    """
    light_theme = {k: v for k, v in theme.items() if k not in ("name", "dark")}
    light_lines = [f"  --{name}: {val};" for name, val in _flat_vars(light_theme)]

    out = "\n".join(light_lines)

    if "dark" in theme:
        dark_lines = [f"    --{name}: {val};" for name, val in _flat_vars(theme["dark"])]
        out += "\n\n@media (prefers-color-scheme: dark) {\n  :root {\n"
        out += "\n".join(dark_lines)
        out += "\n  }\n}"
        out += '\n\n:root[data-theme="dark"] {\n'
        out += "\n".join(dark_lines)
        out += "\n}"

    return out


def theme_path(name: str, themes_dir: Path | None = None) -> Path:
    root = themes_dir or paths.themes_dir()
    return root / f"{name}{THEME_SUFFIX}"


def load_theme(name: str, themes_dir: Path | None = None) -> dict:
    """Load a theme by name. Raises FileNotFoundError / ValueError."""
    import yaml

    path = theme_path(name, themes_dir)
    if not path.exists():
        raise FileNotFoundError(f"Unknown theme: {name}")
    with open(path, "r", encoding="utf-8") as f:
        theme = yaml.safe_load(f) or {}
    if not isinstance(theme, dict):
        raise ValueError(f"Theme file is malformed: {path}")
    return theme


def list_theme_names(themes_dir: Path | None = None) -> list[str]:
    root = themes_dir or paths.themes_dir()
    if not root.exists():
        return []
    return sorted(p.name[: -len(THEME_SUFFIX)] for p in root.glob(f"*{THEME_SUFFIX}"))


def list_themes(themes_dir: Path | None = None) -> list[dict[str, Any]]:
    """Catalog of available themes, with enough detail to pick one."""
    out = []
    for name in list_theme_names(themes_dir):
        try:
            theme = load_theme(name, themes_dir)
        except (ValueError, FileNotFoundError):
            continue
        colors = theme.get("colors", {}) or {}
        modes = ["light"] + (["dark"] if "dark" in theme else [])
        out.append(
            {
                "name": name,
                "label": theme.get("name", name),
                "modes": modes,
                "palette": {
                    **{k: v for k, v in colors.items() if not isinstance(v, dict)},
                    **{f"{k}-{kk}": vv for k, v in colors.items() if isinstance(v, dict) for kk, vv in v.items()},
                },
                "fonts": theme.get("fonts", {}) or {},
            }
        )
    return out
