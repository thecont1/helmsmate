#!/usr/bin/env python3
"""Install HelmsMate for a coding agent.

Does the four things an agent needs, in order, and proves each one:

1. **Checkout** — clone the repository, or use an existing one.
2. **Interpreter** — a Python with PyYAML, in a virtualenv beside the checkout.
3. **MCP server** — register ``helmsmate`` in the client's MCP config.
4. **Skill** — install the companion skill so the agent reaches for HelmsMate
   on its own when a deck is requested.

Then it **verifies**: it speaks the MCP protocol to the server it just
registered, counts the tools, and builds a two-slide deck through
``build_deck``. A deck on disk is the only proof that matters.

Usage::

    python3 scripts/install.py                       # detect the client
    python3 scripts/install.py --client claude       # be explicit
    python3 scripts/install.py --client all          # register everywhere
    python3 scripts/install.py --repo /path/to/checkout --skip-verify

The script is stdlib-only and changes nothing outside the checkout, the
client's MCP config, and the skills directories it names.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

REPO_URL = "https://github.com/thecont1/helmsmate.git"
DEFAULT_DIR = Path.home() / "tools" / "helmsmate"
SKILL_NAME = "helmsmate-decks"
SERVER_NAME = "helmsmate"

EXPECTED_TOOLS = {
    "list_themes",
    "list_layouts",
    "get_deck_schema",
    "validate_deck",
    "build_deck",
    "list_decks",
    "read_deck",
}

OK, WARN, FAIL = "ok", "warn", "fail"


class Step:
    """One line of the install report."""

    def __init__(self, status: str, message: str, detail: str = "") -> None:
        self.status = status
        self.message = message
        self.detail = detail


def say(step: Step) -> None:
    mark = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL "}[step.status]
    print(f"[{mark}] {step.message}")
    if step.detail:
        for line in step.detail.splitlines():
            print(f"         {line}")


# ── 1. checkout ─────────────────────────────────────────────────────────────


def ensure_checkout(target: Path, repo: Path | None) -> tuple[Path, Step]:
    """Return the checkout path and the step describing how it was obtained."""
    if repo is not None:
        repo = repo.expanduser().resolve()
        if not (repo / "helmsmate" / "mcp.py").exists():
            return repo, Step(FAIL, "not a HelmsMate checkout", f"{repo} has no helmsmate/mcp.py")
        return repo, Step(OK, "using the existing checkout", str(repo))

    target = target.expanduser()
    if (target / "helmsmate" / "mcp.py").exists():
        return target.resolve(), Step(OK, "checkout already present", str(target))

    target.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("git") is None:
        return target, Step(FAIL, "git is not installed", "Install git, or pass --repo with a checkout")
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", REPO_URL, str(target)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return target, Step(FAIL, "clone failed", (proc.stderr or "").strip())
    return target.resolve(), Step(OK, "cloned the repository", f"{REPO_URL} → {target}")


# ── 2. interpreter ──────────────────────────────────────────────────────────


def ensure_interpreter(checkout: Path, python: str | None) -> tuple[str, Step]:
    """Return the interpreter the MCP server should run under."""
    if python:
        resolved = shutil.which(python) or str(Path(python).expanduser())
        if not Path(resolved).exists():
            return resolved, Step(FAIL, f"interpreter not found: {resolved}")
        return resolved, Step(OK, "using the given interpreter", resolved)

    venv_dir = checkout / ".venv"
    venv_python = venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python"
    if not venv_python.exists():
        try:
            venv.EnvBuilder(with_pip=True, clear=False).create(venv_dir)
        except Exception as exc:  # noqa: BLE001 — the report is the product
            return sys.executable, Step(FAIL, "could not create a virtualenv", repr(exc))

    proc = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade", "PyYAML"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return str(venv_python), Step(FAIL, "could not install PyYAML", (proc.stderr or "").strip())

    return str(venv_python), Step(OK, "virtualenv ready with PyYAML", str(venv_python))


# ── 3. MCP registration ─────────────────────────────────────────────────────


def mcp_entry(python: str, checkout: Path, workspace: Path) -> dict:
    """The MCP server entry, in the shape every client accepts."""
    return {
        "command": python,
        "args": ["-m", "helmsmate.mcp"],
        "env": {
            "PYTHONPATH": str(checkout),
            "HELMSMATE_WORKSPACE": str(workspace),
        },
    }


def _minimax_entry(python: str, checkout: Path, workspace: Path) -> dict:
    """MiniMax Code keeps a few extra bookkeeping keys per server."""
    entry = mcp_entry(python, checkout, workspace)
    entry.update(
        {
            "type": "stdio",
            "enabled": True,
            "configured": True,
            "builtin": False,
            "description": (
                "HelmsMate — compiles YAML decks into self-contained HTML "
                "presentations. Tools: get_deck_schema, list_layouts, "
                "list_themes, validate_deck, build_deck, list_decks, read_deck."
            ),
        }
    )
    return entry


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def register(clients: list[str], python: str, checkout: Path, workspace: Path) -> list[Step]:
    """Write the server entry into each client's MCP config."""
    steps: list[Step] = []
    targets: list[tuple[str, Path, object]] = []

    for client in clients:
        if client == "minimax":
            targets.append(("MiniMax Code", Path.home() / ".minimax" / "mcp.json", _minimax_entry))
        elif client == "claude":
            targets.append(("Claude Code (user)", Path.home() / ".claude.json", mcp_entry))
            targets.append(("Claude Code (project)", Path.cwd() / ".mcp.json", mcp_entry))
        elif client == "cursor":
            targets.append(("Cursor (user)", Path.home() / ".cursor" / "mcp.json", mcp_entry))
            targets.append(("Cursor (project)", Path.cwd() / ".cursor" / "mcp.json", mcp_entry))

    for label, path, builder in targets:
        data = _read_json(path)
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            servers = {}
            data["mcpServers"] = servers
        servers[SERVER_NAME] = builder(python, checkout, workspace)
        _write_json(path, data)
        steps.append(Step(OK, f"registered with {label}", str(path)))

    return steps


def detect_clients() -> list[str]:
    """Which clients have a config on this machine."""
    probes = {
        "minimax": Path.home() / ".minimax" / "mcp.json",
        "claude": Path.home() / ".claude.json",
        "cursor": Path.home() / ".cursor" / "mcp.json",
    }
    found = [name for name, probe in probes.items() if probe.exists()]
    if (Path.cwd() / ".mcp.json").exists():
        found.append("claude")
    if (Path.cwd() / ".cursor" / "mcp.json").exists():
        found.append("cursor")
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(found))


# ── 4. the companion skill ──────────────────────────────────────────────────


def install_skill(checkout: Path, clients: list[str]) -> list[Step]:
    """Install the skill so the agent reaches for HelmsMate on its own."""
    steps: list[Step] = []
    source = checkout / "skills" / SKILL_NAME / "SKILL.md"
    if not source.exists():
        return [Step(WARN, "no companion skill in this checkout", str(source))]

    agents_root = Path.home() / ".agents" / "skills"
    canonical = agents_root / SKILL_NAME
    canonical.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, canonical / "SKILL.md")
    steps.append(Step(OK, "installed the companion skill", str(canonical / "SKILL.md")))

    # MiniMax Code discovers skills through its own directory; the existing
    # convention there is a relative symlink into ~/.agents/skills.
    mcode_skills = Path.home() / ".minimax" / "skills"
    if mcode_skills.is_dir():
        link = mcode_skills / SKILL_NAME
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(Path("..") / ".." / ".agents" / "skills" / SKILL_NAME)
            steps.append(Step(OK, "linked the skill for MiniMax Code", str(link)))
        except OSError as exc:
            steps.append(Step(WARN, "could not link the skill for MiniMax Code", repr(exc)))

    for client, folder in (("claude", ".claude/skills"), ("cursor", ".cursor/skills")):
        if client not in clients:
            continue
        dest = Path.home() / folder / SKILL_NAME
        try:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest / "SKILL.md")
            steps.append(Step(OK, f"installed the skill for {client}", str(dest / "SKILL.md")))
        except OSError as exc:
            steps.append(Step(WARN, f"could not install the skill for {client}", repr(exc)))

    return steps


# ── 5. verification ─────────────────────────────────────────────────────────


def _rpc(proc: subprocess.Popen, message: dict) -> dict:
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("the server closed its output stream")
    return json.loads(line)


def verify(python: str, checkout: Path, workspace: Path) -> list[Step]:
    """Speak MCP to the server, then build a deck through it."""
    steps: list[Step] = []
    env = dict(os.environ)
    env["PYTHONPATH"] = str(checkout)
    env["HELMSMATE_WORKSPACE"] = str(workspace)

    try:
        proc = subprocess.Popen(
            [python, "-m", "helmsmate.mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(checkout),
            env=env,
        )
    except OSError as exc:
        return [Step(FAIL, "could not start the MCP server", repr(exc))]

    try:
        init = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
        )
        server = init.get("result", {}).get("serverInfo", {})
        steps.append(
            Step(
                OK,
                f"the server answered: {server.get('name', '?')} {server.get('version', '')}".strip(),
                f"protocol {init.get('result', {}).get('protocolVersion', '?')}",
            )
        )

        listed = _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = {t["name"] for t in listed.get("result", {}).get("tools", [])}
        missing = EXPECTED_TOOLS - tools
        if missing:
            steps.append(Step(FAIL, "the server did not expose every tool", ", ".join(sorted(missing))))
        else:
            steps.append(Step(OK, f"all {len(tools)} tools are exposed", ", ".join(sorted(tools))))

        deck = {
            "deck": {"title": "HelmsMate install check", "chrome": False},
            "theme": "mariners-chart",
            "slides": [
                {
                    "layout": "opener",
                    "context": "Install check",
                    "eyebrow": "HelmsMate",
                    "title": "It is wired up.",
                    "lede": "This deck was built over MCP by the installer, to prove the loop works.",
                    "stats": [{"big": str(len(tools)), "small": "tools exposed"}],
                },
                {
                    "layout": "closer",
                    "context": "Install check",
                    "eyebrow": "Ready",
                    "title": "Ask for a deck.",
                    "lede": "The agent now reaches for HelmsMate on its own.",
                    "lede2": "Delete this deck whenever you like — it was only a proof.",
                },
            ],
        }
        built = _rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "build_deck", "arguments": {"deck": deck}},
            },
        )
        payload = built.get("result", {}).get("structuredContent") or {}
        if not payload.get("ok"):
            steps.append(Step(FAIL, "build_deck failed", json.dumps(payload.get("errors", payload))[:400]))
        else:
            html = Path(payload["html_path"])
            if html.exists() and html.stat().st_size > 0:
                steps.append(
                    Step(OK, f"built a {payload['slides']}-slide deck", f"{html} ({payload['bytes']:,} bytes)"),
                )
            else:
                steps.append(Step(FAIL, "build_deck reported success but wrote no file", payload["html_path"]))
    except Exception as exc:  # noqa: BLE001 — the report is the product
        steps.append(Step(FAIL, "the MCP round trip failed", repr(exc)))
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    return steps


# ── the run ─────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install HelmsMate for a coding agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--client",
        default="auto",
        choices=["auto", "minimax", "claude", "cursor", "all"],
        help="which coding agent to register with (default: auto-detect)",
    )
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help=f"checkout location (default: {DEFAULT_DIR})")
    parser.add_argument("--repo", type=Path, help="use an existing checkout instead of cloning")
    parser.add_argument("--workspace", type=Path, help="where built decks are stored (default: <checkout>/decks)")
    parser.add_argument("--python", help="interpreter for the MCP server (default: <checkout>/.venv/bin/python)")
    parser.add_argument("--skip-verify", action="store_true", help="do not run the MCP round trip")
    args = parser.parse_args(argv)

    print("HelmsMate installer")
    print("=" * 60)

    steps: list[Step] = []

    checkout, step = ensure_checkout(args.dir, args.repo)
    steps.append(step)
    if step.status == FAIL:
        for s in steps:
            say(s)
        return 1

    workspace = (args.workspace or checkout / "decks").expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    python, step = ensure_interpreter(checkout, args.python)
    steps.append(step)
    if step.status == FAIL:
        for s in steps:
            say(s)
        return 1

    if args.client == "auto":
        clients = detect_clients()
        if not clients:
            steps.append(
                Step(
                    WARN,
                    "no coding agent config found on this machine",
                    "Re-run with --client minimax | claude | cursor | all",
                )
            )
        else:
            steps.extend(register(clients, python, checkout, workspace))
    else:
        clients = ["minimax", "claude", "cursor"] if args.client == "all" else [args.client]
        steps.extend(register(clients, python, checkout, workspace))

    steps.extend(install_skill(checkout, clients))

    if not args.skip_verify:
        steps.extend(verify(python, checkout, workspace))

    print("=" * 60)
    for s in steps:
        say(s)

    failed = [s for s in steps if s.status == FAIL]
    print("=" * 60)
    if failed:
        print(f"{len(failed)} step(s) failed. HelmsMate is not ready.")
        return 1

    print("HelmsMate is ready.")
    print(f"  checkout   {checkout}")
    print(f"  server     {python} -m helmsmate.mcp")
    print(f"  workspace  {workspace}")
    print("  restart your coding agent, then ask it for a deck.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
