"""hyperspace/venv_paths.py — where a virtual environment keeps its
interpreter on each OS, and the one path every caller names on every OS.

A venv keeps its interpreter at `bin/python` on macOS and Linux and at
`Scripts\\python.exe` on Windows. Rather than teach every caller that
difference — `.mcp.json` (which has no per-platform field), each skill's
commands, the launchers, the docs — provisioning makes ONE spelling true
everywhere: `env/bin/python`. It is native on POSIX; on Windows `env/bin` is a
directory junction to `env/Scripts`, and every Windows spawner resolves the
extensionless name to `python.exe` (Claude Code's MCP spawner, CreateProcess,
libuv, cmd, PowerShell 5.1/7 and Git Bash — verified on a `windows-latest`
runner; see `docs/reference/tripwires.md`, "the `env/bin` contract").

Stdlib only, and imported by `hyperspace.setup.provision` — which must run on
a bare interpreter before any of this project's dependencies are installed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

WINDOWS = "win32"


def native_python(env_dir: str | Path, platform: str | None = None) -> Path:
    """The interpreter a freshly created venv actually contains on
    `platform` (a `sys.platform` string; defaults to the running one)."""
    platform = sys.platform if platform is None else platform
    if platform == WINDOWS:
        return Path(env_dir) / "Scripts" / "python.exe"
    return Path(env_dir) / "bin" / "python"


def portable_python(env_dir: str | Path) -> Path:
    """`env/bin/python` — the spelling `.mcp.json`, the skills and the POSIX
    launchers use on every OS. Extensionless on purpose: on Windows it
    resolves to `env\\bin\\python.exe` through the junction
    `link_bin_to_scripts` creates."""
    return Path(env_dir) / "bin" / "python"


def find_venv_python(venv_dir: str | Path) -> Path | None:
    """The first interpreter present under `venv_dir` in either layout —
    for venvs this project did not create (e.g. a repository's own `.venv`
    the verifier's `command_check` runs tests with)."""
    venv_dir = Path(venv_dir)
    for rel in (("bin", "python3"), ("bin", "python"), ("Scripts", "python.exe")):
        candidate = venv_dir.joinpath(*rel)
        if candidate.is_file():
            return candidate
    return None


def _create_junction(target: str, link: str) -> None:
    """An NTFS directory junction `link` -> `target`. Junctions, unlike
    symlinks, need neither administrator rights nor Developer Mode.
    `_winapi.CreateJunction` is CPython's own (used by its test suite);
    `mklink /J` is the documented fallback if a build lacks it."""
    try:
        import _winapi  # type: ignore[import-not-found]

        _winapi.CreateJunction(target, link)
        return
    except (ImportError, AttributeError):
        pass
    proc = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", link, target], capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise OSError(proc.stderr.strip() or proc.stdout.strip() or f"mklink exited {proc.returncode}")


def link_bin_to_scripts(
    env_dir: str | Path,
    platform: str | None = None,
    *,
    create_junction: Callable[[str, str], None] = _create_junction,
) -> tuple[bool, str]:
    """Makes `portable_python(env_dir)` reach the venv's interpreter.
    POSIX: nothing to do. Windows: creates `env/bin` as a junction to
    `env/Scripts`; idempotent — a `bin` that already reaches `python.exe` is
    left alone. Returns `(ok, message)` and never raises, so provisioning can
    record the outcome as one more step."""
    platform = sys.platform if platform is None else platform
    if platform != WINDOWS:
        return True, "env/bin is the venv's own layout — link not needed"

    env_dir = Path(env_dir)
    native = native_python(env_dir, platform)
    if not native.is_file():
        return False, f"cannot link env/bin: {native} does not exist"

    bin_dir = env_dir / "bin"
    if (bin_dir / "python.exe").is_file():
        return True, f"{bin_dir} already reaches {native.name}"
    if os.path.lexists(bin_dir):
        return False, f"{bin_dir} exists but does not contain python.exe — remove it and re-run setup"

    try:
        create_junction(str(native.parent), str(bin_dir))
    except OSError as exc:
        return False, f"could not create junction {bin_dir} -> {native.parent}: {exc}"
    if not (bin_dir / "python.exe").is_file():
        return False, f"junction {bin_dir} -> {native.parent} was created but does not reach python.exe"
    return True, f"junction {bin_dir} -> {native.parent}"
