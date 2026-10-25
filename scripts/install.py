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
import tempfile
import threading
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

# Every subprocess the installer runs is bounded — a stalled clone, a hung pip
# or a silent MCP server must not block the install forever.
CLONE_TIMEOUT = 600
PIP_TIMEOUT = 300
RPC_TIMEOUT = 60


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
    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", REPO_URL, str(target)],
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return target, Step(
            FAIL,
            "clone timed out",
            f"No response in {CLONE_TIMEOUT}s from {REPO_URL}",
        )
    except OSError as exc:
        return target, Step(FAIL, "could not run git", repr(exc))
    if proc.returncode != 0:
        return target, Step(FAIL, "clone failed", (proc.stderr or "").strip())
    return target.resolve(), Step(OK, "cloned the repository", f"{REPO_URL} → {target}")


# ── 2. interpreter ──────────────────────────────────────────────────────────


def ensure_interpreter(checkout: Path, python: str | None) -> tuple[str, Step]:
    """Return the interpreter the MCP server should run under."""
    if python:
        found = shutil.which(python)
        # abspath, not resolve: resolving would follow the venv's symlink to
        # the base interpreter and lose the virtualenv's site-packages.
        resolved = os.path.abspath(os.path.expanduser(found or python))
        if not os.path.isfile(resolved):
            return resolved, Step(FAIL, f"interpreter not found: {resolved}")
        return resolved, Step(OK, "using the given interpreter", resolved)

    venv_dir = checkout / ".venv"
    venv_python = venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python"
    if not venv_python.exists():
        try:
            venv.EnvBuilder(with_pip=True, clear=False).create(venv_dir)
        except Exception as exc:  # noqa: BLE001 — the report is the product
            return sys.executable, Step(FAIL, "could not create a virtualenv", repr(exc))

    try:
        proc = subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade", "PyYAML"],
            capture_output=True,
            text=True,
            timeout=PIP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return str(venv_python), Step(
            FAIL,
            "pip install timed out",
            f"No response in {PIP_TIMEOUT}s — check the network and retry",
        )
    except OSError as exc:
        return str(venv_python), Step(FAIL, "could not run pip", repr(exc))
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


class ConfigError(Exception):
    """A client's config file exists but could not be understood."""


def _read_json(path: Path) -> dict:
    """Read a client's JSON config.

    A missing file is an empty config. A malformed one is an error: silently
    treating it as empty would let the next write destroy whatever the client
    was already configured with.
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path} could not be read: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not contain a JSON object")
    return data


def _write_json(path: Path, data: dict) -> None:
    """Write a config atomically.

    A plain write truncates the target first, so a failure part-way through
    would leave the user with a broken config — and every other server they
    had configured in it lost. Stage the file beside the target, then swap it
    in only once the write has succeeded.
    """
    # A client config may be a symlink into a dotfiles repo. Replacing the
    # symlink would break it and leave the real config untouched, so write
    # through to the target and leave the symlink exactly as it is.
    target = path.resolve() if path.is_symlink() else path

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2) + "\n"
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o644

    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


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
        try:
            data = _read_json(path)
        except ConfigError as exc:
            # Leave the file exactly as it is — the user's other settings in it
            # are still theirs to keep.
            steps.append(Step(FAIL, f"could not read the {label} config", str(exc)))
            continue
        servers = data.get("mcpServers", {})
        if not isinstance(servers, dict):
            # Not ours to reinterpret. Replacing it would destroy whatever the
            # client had there, so leave the file alone and say so.
            steps.append(
                Step(
                    FAIL,
                    f"the {label} config has a non-object 'mcpServers'",
                    "Left the file unchanged — repair the value by hand, then re-run",
                )
            )
            continue
        servers[SERVER_NAME] = builder(python, checkout, workspace)
        data["mcpServers"] = servers
        try:
            _write_json(path, data)
        except OSError as exc:
            steps.append(Step(FAIL, f"could not write the {label} config", repr(exc)))
            continue
        steps.append(Step(OK, f"registered with {label}", str(path)))

    return steps


def _present(path: Path) -> bool:
    """A config counts if it exists — or is a symlink, even a broken one.

    `Path.exists()` follows symlinks, so a link pointing at a file that is
    not there yet reads as absent. The user has that client pointed at a
    config all the same, and the write resolves the link and creates the
    target.
    """
    return path.exists() or path.is_symlink()


def detect_clients() -> list[str]:
    """Which clients have a config on this machine."""
    probes = {
        "minimax": Path.home() / ".minimax" / "mcp.json",
        "claude": Path.home() / ".claude.json",
        "cursor": Path.home() / ".cursor" / "mcp.json",
    }
    found = [name for name, probe in probes.items() if _present(probe)]
    if _present(Path.cwd() / ".mcp.json"):
        found.append("claude")
    if _present(Path.cwd() / ".cursor" / "mcp.json"):
        found.append("cursor")
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(found))


# ── 4. the companion skill ──────────────────────────────────────────────────


def install_skill(checkout: Path, clients: list[str]) -> list[Step]:
    """Install the skill so the agent reaches for HelmsMate on its own."""
    steps: list[Step] = []
    source = checkout / "skills" / SKILL_NAME / "SKILL.md"
    if not source.exists():
        # Without the skill the agent has the tools but no reason to reach for
        # them — the install is incomplete, not merely untidy.
        return [Step(FAIL, "no companion skill in this checkout", str(source))]

    agents_root = Path.home() / ".agents" / "skills"
    canonical = agents_root / SKILL_NAME
    try:
        canonical.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, canonical / "SKILL.md")
        steps.append(Step(OK, "installed the companion skill", str(canonical / "SKILL.md")))
    except OSError as exc:
        steps.append(Step(FAIL, "could not install the companion skill", repr(exc)))

    # MiniMax Code discovers skills through its own directory; the existing
    # convention there is a relative symlink into ~/.agents/skills. If MiniMax
    # was asked for, create the directory rather than skipping the link.
    mcode_skills = Path.home() / ".minimax" / "skills"
    if "minimax" in clients or mcode_skills.is_dir():
        link = mcode_skills / SKILL_NAME
        try:
            mcode_skills.mkdir(parents=True, exist_ok=True)
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(Path("..") / ".." / ".agents" / "skills" / SKILL_NAME)
            steps.append(Step(OK, "linked the skill for MiniMax Code", str(link)))
        except OSError as exc:
            steps.append(Step(FAIL, "could not link the skill for MiniMax Code", repr(exc)))

    for client, folder in (("claude", ".claude/skills"), ("cursor", ".cursor/skills")):
        if client not in clients:
            continue
        dest = Path.home() / folder / SKILL_NAME
        try:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest / "SKILL.md")
            steps.append(Step(OK, f"installed the skill for {client}", str(dest / "SKILL.md")))
        except OSError as exc:
            steps.append(Step(FAIL, f"could not install the skill for {client}", repr(exc)))

    return steps


# ── 5. verification ─────────────────────────────────────────────────────────


def _read_line(stream, box: list[str]) -> None:
    """Read one line into `box`. The thread only reports what it managed to read."""
    try:
        box.append(stream.readline())
    except Exception:  # noqa: BLE001 — a closed pipe is just an empty line here
        box.append("")


def _rpc(proc: subprocess.Popen, message: dict, timeout: float = RPC_TIMEOUT) -> dict:
    """Send one JSON-RPC message and wait for its reply, with a deadline.

    A read on a pipe has no timeout of its own, so the read happens on a
    thread. If the server goes quiet the child is stopped rather than the
    install hanging on it forever.
    """
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()

    box: list[str] = []
    reader = threading.Thread(target=_read_line, args=(proc.stdout, box), daemon=True)
    reader.start()
    reader.join(timeout)

    if reader.is_alive():
        proc.terminate()
        raise TimeoutError(f"no reply within {timeout:.0f}s")
    if not box or not box[0]:
        raise RuntimeError("the server closed its output stream")
    return json.loads(box[0])


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
            steps.append(
                Step(
                    FAIL,
                    "nothing was registered with any client",
                    "Pick the client you use: --client minimax | claude | cursor | all",
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
