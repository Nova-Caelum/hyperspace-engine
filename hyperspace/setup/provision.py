"""hyperspace/setup/provision.py — the functions behind the `hyperspace-setup`
skill and `hyperspace doctor` (row T5.1).

Every external boundary — `uv`/`venv`/`pip` subprocesses, `claude`/`codex`
presence and probing, which platform's launcher to write — comes in through
an injected `run`/`which`/`platform` parameter so `tests/test_setup.py` never
needs a real `uv`, `claude`, `codex`, or network call; production code paths
supply the real `subprocess.run` / `shutil.which` / `sys.platform`.

Credential hygiene (brief, INC024/INC025): `probe_judges` reads
`OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` only as booleans (`bool(env.get(...))`)
— the value itself is never read into a variable that could be printed,
logged, or returned.

Import-chain note (found empirically, not assumed — frame-discipline Context
2): this module's own top level imports ONLY `hyperspace.config` (stdlib
`tomllib`) — never `hyperspace.http.server`, `hyperspace.store`,
`hyperspace.tools`, or `hyperspace.contracts`, all of which pull in this
project's PyPI dependencies (pydantic, etc.) that are NOT installed until
`provision_env` finishes. `hyperspace.cli` imports `hyperspace.http.server`
at ITS OWN top level (pre-existing, not this row's code), so `python3 -m
hyperspace.cli` cannot run before the isolated environment exists; this is
exactly why `hyperspace/setup/__main__.py` exists as a second, dependency-free
entrypoint for that one bootstrap moment (`is_bound` is imported lazily
inside `doctor()` below for the same reason — `doctor` always runs from
INSIDE the provisioned environment, so the lazy import costs nothing there).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from .._pyfloor import MIN_PYTHON
from ..config import write_config
from ..venv_paths import WINDOWS, link_bin_to_scripts, native_python, portable_python

_NPM_INSTALL_CMD = "npm install -g @anthropic-ai/claude-code"
_PROBE_TIMEOUT_SECONDS = 30

_LAUNCHER_FILES: dict[str, tuple[str, int | None]] = {
    "darwin": ("Open Hyperspace.command", 0o755),
    "win32": ("Open Hyperspace.bat", None),
    "linux": ("open-hyperspace.sh", 0o755),
}
_DEFAULT_LAUNCHER_PLATFORM = "linux"

_LAUNCHER_TEMPLATES_DIR = Path(__file__).resolve().parent / "launcher_templates"


def _plugin_root() -> Path:
    """The repo/plugin root: `hyperspace/setup/provision.py` sits two levels
    under it (`setup/` -> `hyperspace/` -> root), so `parents[2]` resolves it
    whether this file is running from the worktree or an installed copy —
    the same root either way, since `pip install <root>` copies this file
    unchanged."""
    return Path(__file__).resolve().parents[2]


# ── (b) Python version check ────────────────────────────────────────────


def check_python(version_info: tuple | None = None) -> tuple[bool, str]:
    """`version_info` defaults to the running interpreter's own
    `sys.version_info`; a test injects a fake tuple to exercise the refusal
    without needing a second Python on the machine."""
    version_info = sys.version_info if version_info is None else version_info
    version_str = ".".join(str(part) for part in tuple(version_info)[:3])
    required_str = ".".join(str(part) for part in MIN_PYTHON)
    if tuple(version_info)[:2] >= MIN_PYTHON:
        return True, f"python {version_str} OK (requires >= {required_str})"
    return False, (
        f"python {version_str} found, but hyperspace requires Python >= {required_str} "
        "— install a newer Python and re-run setup"
    )


# ── (a) isolated environment ─────────────────────────────────────────────


def _rc(proc: Any) -> int:
    return getattr(proc, "returncode", 1)


def provision_env(
    project_dir: str | Path,
    *,
    prefer_uv: bool = True,
    run: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    platform: str | None = None,
    link: Callable[[Path, str], tuple[bool, str]] = link_bin_to_scripts,
) -> dict:
    """Creates `<project_dir>/.hyperspace/env` and installs this plugin's own
    tree into it — `uv venv` + `uv pip install` when `uv` is on PATH (and
    `prefer_uv` is true), stdlib `venv` + `pip install` otherwise. Records
    which tool ran and every subprocess's exit code so a caller (or a test)
    can tell exactly what happened without re-deriving it from side effects.

    `uv venv` is pinned to `sys.executable` — the interpreter `check_python`
    just vetted — rather than whatever `uv` would discover first. On Windows
    (`platform == "win32"`) the install targets `env/Scripts/python.exe`, and
    a final step links `env/bin` to `env/Scripts` so the one spelling
    `.mcp.json` and every skill use, `.hyperspace/env/bin/python`, resolves
    there too (`hyperspace/venv_paths.py`).
    """
    platform = sys.platform if platform is None else platform
    project_dir = Path(project_dir)
    env_dir = project_dir / ".hyperspace" / "env"
    plugin_root = _plugin_root()
    python_path = native_python(env_dir, platform)

    use_uv = prefer_uv and which("uv") is not None
    tool = "uv" if use_uv else "venv"
    steps: list[dict] = []

    if use_uv:
        create_proc = run(
            ["uv", "venv", str(env_dir), "--python", sys.executable], capture_output=True, text=True,
        )
        steps.append({"command": f"uv venv {env_dir} --python {sys.executable}", "exit_code": _rc(create_proc)})
        if _rc(create_proc) == 0:
            install_proc = run(
                ["uv", "pip", "install", "--python", str(python_path), str(plugin_root)],
                capture_output=True, text=True,
            )
            steps.append({
                "command": f"uv pip install --python {python_path} {plugin_root}",
                "exit_code": _rc(install_proc),
            })
    else:
        create_proc = run([sys.executable, "-m", "venv", str(env_dir)], capture_output=True, text=True)
        steps.append({"command": f"{sys.executable} -m venv {env_dir}", "exit_code": _rc(create_proc)})
        if _rc(create_proc) == 0:
            install_proc = run(
                [str(python_path), "-m", "pip", "install", str(plugin_root)],
                capture_output=True, text=True,
            )
            steps.append({
                "command": f"{python_path} -m pip install {plugin_root}",
                "exit_code": _rc(install_proc),
            })

    if platform == WINDOWS and steps and all(step["exit_code"] == 0 for step in steps):
        linked, message = link(env_dir, platform)
        steps.append({"command": "link env/bin -> env/Scripts", "exit_code": 0 if linked else 1, "message": message})

    ok = bool(steps) and all(step["exit_code"] == 0 for step in steps)
    return {"tool": tool, "ok": ok, "steps": steps, "env_dir": str(env_dir)}


# ── (c) judge probing + selection ────────────────────────────────────────


def probe_judges(
    env: Mapping[str, str],
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., Any] = subprocess.run,
) -> dict:
    """Boolean-only presence checks — `env`'s key VALUES are never read into
    a variable, printed, or returned; only `bool(env.get(...))` crosses this
    function's boundary (credential hygiene, INC024/INC025).

    CLI presence is a `which()` call; a working `claude` additionally gets a
    guarded, timed-out `claude -p ping --output-format json` (register A19 —
    unverified end to end at authoring time, so a failure here is
    informative, not fatal: `select_judge` reads it and falls back)."""
    probes: dict[str, Any] = {
        "openrouter_key": bool(env.get("OPENROUTER_API_KEY")),
        "anthropic_key": bool(env.get("ANTHROPIC_API_KEY")),
    }

    # Every probe runs the path `which` resolved, never the bare name: on
    # Windows an npm-installed CLI is a `.cmd` shim that `which` finds via
    # PATHEXT but CreateProcess cannot find by bare name.
    claude_path = which("claude")
    claude_info: dict[str, Any] = {"present": claude_path is not None, "version_ok": False, "ping_ok": False}
    if claude_path is not None:
        try:
            version_proc = run([claude_path, "--version"], capture_output=True, text=True, timeout=_PROBE_TIMEOUT_SECONDS)
            claude_info["version_ok"] = _rc(version_proc) == 0
        except (subprocess.TimeoutExpired, OSError):
            claude_info["version_ok"] = False
        try:
            ping_proc = run(
                [claude_path, "-p", "ping", "--output-format", "json"],
                capture_output=True, text=True, timeout=_PROBE_TIMEOUT_SECONDS,
            )
            claude_info["ping_ok"] = _rc(ping_proc) == 0
        except (subprocess.TimeoutExpired, OSError):
            claude_info["ping_ok"] = False
    probes["claude"] = claude_info

    codex_path = which("codex")
    codex_info: dict[str, Any] = {"present": codex_path is not None, "version_ok": False}
    if codex_path is not None:
        try:
            version_proc = run([codex_path, "--version"], capture_output=True, text=True, timeout=_PROBE_TIMEOUT_SECONDS)
            codex_info["version_ok"] = _rc(version_proc) == 0
        except (subprocess.TimeoutExpired, OSError):
            codex_info["version_ok"] = False
    probes["codex"] = codex_info

    return probes


def select_judge(probes: Mapping[str, Any]) -> tuple[str, str | None]:
    """Picks the least-friction runner the probes found, and — when none is
    usable — a fallback message naming what was missing so the skill can say
    so out loud (the verifier never silently switches judge). Priority:
    an already-working key beats a CLI that still needs a login or an
    install; `codex` before `none` for a working but keyless CLI; `none`
    (with a message) is always last and always available."""
    if probes.get("openrouter_key"):
        return "openrouter", None
    if probes.get("anthropic_key"):
        return "anthropic", None

    claude = probes.get("claude", {})
    if claude.get("present") and claude.get("ping_ok"):
        return "claude-code", None

    codex = probes.get("codex", {})
    if codex.get("present") and codex.get("version_ok"):
        return "codex", None

    if claude.get("present"):
        message = (
            "`claude` is on PATH but did not respond to a ping (`claude -p ping`) "
            f"— this can happen if it needs a fresh install ({_NPM_INSTALL_CMD}) or "
            "if it is not logged in (run `claude login`). Falling back to judge=none; "
            "deterministic criteria (file_state, command_check) still verify."
        )
        return "none", message

    message = (
        "No OPENROUTER_API_KEY, no ANTHROPIC_API_KEY, and no claude/codex CLI found "
        "on PATH — falling back to judge=none. Deterministic criteria (file_state, "
        f"command_check) still verify; set a key or install a CLI ({_NPM_INSTALL_CMD}) "
        "to enable LLM judging."
    )
    return "none", message


# ── (d) launcher ─────────────────────────────────────────────────────────


def write_launcher(project_dir: str | Path, platform: str) -> Path:
    """Writes the double-clickable launcher for `platform` (a `sys.platform`
    string: `darwin`, `win32`, or anything else treated as Linux) into
    `<project_dir>/.hyperspace/`, copied verbatim from the package-data
    template — executable on macOS/Linux, not on Windows (`.bat` files carry
    no POSIX execute bit)."""
    project_dir = Path(project_dir)
    key = platform if platform in _LAUNCHER_FILES else _DEFAULT_LAUNCHER_PLATFORM
    filename, mode = _LAUNCHER_FILES[key]

    template_path = _LAUNCHER_TEMPLATES_DIR / filename
    dest_dir = project_dir / ".hyperspace"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    dest_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
    if mode is not None:
        dest_path.chmod(mode)
    return dest_path


# ── orchestrator: everything the skill's non-interactive path needs ─────


def provision(
    project_dir: str | Path,
    *,
    judge: str | None = None,
    port: int | None = None,
    user: str | None = None,
    prefer_uv: bool = True,
    run: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    version_info: tuple | None = None,
) -> dict:
    """Ties (a)-(d) together into the one call the CLI's `init --provision`
    flag and the installer probe both make: checks Python, provisions the
    isolated env, resolves the judge (an explicit `judge` skips probing
    entirely — the non-interactive path), writes `.hyperspace/config.toml`,
    writes the launcher. Stops after the Python check if it fails; every
    other step's result key is `None` in that case."""
    platform = sys.platform if platform is None else platform
    env = {} if env is None else env

    python_ok, python_message = check_python(version_info)
    result: dict[str, Any] = {"python": {"ok": python_ok, "message": python_message}}
    if not python_ok:
        result.update({"env": None, "judge": None, "config_path": None, "launcher_path": None})
        return result

    env_result = provision_env(project_dir, prefer_uv=prefer_uv, run=run, which=which, platform=platform)
    result["env"] = env_result

    if judge is not None:
        chosen_judge, message = judge, None
        probes = None
    else:
        probes = probe_judges(env, which=which, run=run)
        chosen_judge, message = select_judge(probes)

    result["judge"] = {"judge": chosen_judge, "message": message, "probes": probes}

    config_kwargs: dict[str, Any] = {"judge": chosen_judge}
    if port is not None:
        config_kwargs["port"] = port
    if user is not None:
        config_kwargs["user"] = user
    config_path = write_config(project_dir, **config_kwargs)
    result["config_path"] = str(config_path)

    launcher_path = write_launcher(project_dir, platform)
    result["launcher_path"] = str(launcher_path)

    return result


def provision_and_report(
    project_dir: str | Path,
    *,
    judge: str | None = None,
    port: int | None = None,
    user: str | None = None,
    **provision_kwargs: Any,
) -> int:
    """`provision()` plus the print-and-exit-code shape both CLI entrypoints
    need — `hyperspace init --provision` (inside `hyperspace/cli.py`, run
    from INSIDE an already-provisioned environment) and `python3 -m
    hyperspace.setup --provision` (`hyperspace/setup/__main__.py`, the one
    that runs BEFORE the environment exists). One copy of the reporting
    logic; two callers, so it can never drift between them."""
    result = provision(project_dir, judge=judge, port=port, user=user, **provision_kwargs)
    if not result["python"]["ok"]:
        print(f"FAIL python: {result['python']['message']}", file=sys.stderr)
        return 1

    env_info = result["env"]
    print(f"provisioned .hyperspace/env with {env_info['tool']} ({'OK' if env_info['ok'] else 'FAILED'})")
    judge_info = result["judge"]
    print(f"judge = {judge_info['judge']}")
    if judge_info["message"]:
        print(judge_info["message"])
    print(f"wrote {result['config_path']}")
    print(f"wrote {result['launcher_path']}")
    return 0 if env_info["ok"] else 1


# ── doctor ────────────────────────────────────────────────────────────────


def _door_responds(port: int, host: str = "127.0.0.1") -> bool:
    """True if something on `host:port` answers `GET /api/projects` with a
    200 — used to tell "our door is already up" apart from "something else
    has this port"."""
    import json
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/projects", timeout=2) as resp:
            if resp.status != 200:
                return False
            json.loads(resp.read())
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _check_env(env_dir: Path, platform: str) -> tuple[bool, str]:
    """The venv's own interpreter exists — and, on Windows, `env/bin` reaches
    it, because `.mcp.json` and every skill run `.hyperspace/env/bin/python`
    (a missing junction leaves the MCP server unable to start)."""
    native = native_python(env_dir, platform)
    if not native.is_file():
        return False, f"missing {native}"
    if platform != WINDOWS:
        return True, f"found {native}"
    portable = portable_python(env_dir)
    if not portable.with_name("python.exe").is_file():
        return False, (
            f"found {native}, but {portable} does not reach it — the env/bin junction is missing; "
            "re-run the hyperspace-setup skill"
        )
    return True, f"found {native} (reachable as {portable})"


def doctor(project_dir: str | Path, platform: str | None = None) -> tuple[bool, list[str]]:
    """Re-runs the setup skill's check phase: python, env, store, config/judge,
    door port free-or-ours. Returns `(all_ok, lines)` — one `OK`/`FAIL` line
    per check, in that order; the CLI prints the lines and exits 0 only when
    every one reads `OK`. `platform` (a `sys.platform` string) selects which
    venv layout to expect; it defaults to the running one."""
    from ..config import load_config
    from ..http.server import is_bound  # lazy: doctor always runs post-provisioning

    platform = sys.platform if platform is None else platform
    project_dir = Path(project_dir)
    hyperspace_dir = project_dir / ".hyperspace"
    lines: list[str] = []
    checks: list[bool] = []

    python_ok, python_message = check_python()
    lines.append(f"{'OK' if python_ok else 'FAIL'} python: {python_message}")
    checks.append(python_ok)

    env_ok, env_message = _check_env(hyperspace_dir / "env", platform)
    lines.append(f"{'OK' if env_ok else 'FAIL'} env: {env_message}")
    checks.append(env_ok)

    db_path = hyperspace_dir / "graph.db"
    store_ok = db_path.is_file()
    lines.append(f"{'OK' if store_ok else 'FAIL'} store: {'found' if store_ok else 'missing'} {db_path}")
    checks.append(store_ok)

    try:
        cfg = load_config(project_dir)
        config_ok = True
        config_message = f"judge={cfg.judge} port={cfg.port}"
    except ValueError as exc:
        config_ok = False
        config_message = str(exc)
        cfg = None
    lines.append(f"{'OK' if config_ok else 'FAIL'} config/judge: {config_message}")
    checks.append(config_ok)

    port = cfg.port if cfg is not None else 8791
    if not is_bound(port):
        door_ok = True
        door_message = f"port {port} free"
    else:
        door_ok = _door_responds(port)
        door_message = f"port {port} in use — {'this looks like our own door' if door_ok else 'occupied by something else'}"
    lines.append(f"{'OK' if door_ok else 'FAIL'} door: {door_message}")
    checks.append(door_ok)

    return all(checks), lines
