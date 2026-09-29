"""v0.1.3 — where a virtual environment keeps its interpreter, per OS, and the
one path every caller names regardless of OS (`hyperspace/venv_paths.py`).

A Windows venv keeps its interpreter at `env/Scripts/python.exe`; macOS and
Linux at `env/bin/python`. `.mcp.json`, every skill command and the POSIX
launchers name `env/bin/python` on every OS; on Windows provisioning makes that
path real with a directory junction `env/bin -> env/Scripts`, and every Windows
spawner resolves the extensionless name to `python.exe` (WINDOWS_FACTS F4).

Platform is always injected here — a fake `sys.platform` string — so the
Windows branch is exercised on every OS; the one test that needs a real
junction runs only where junctions exist, and says so.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hyperspace.venv_paths import (
    find_venv_python,
    link_bin_to_scripts,
    native_python,
    portable_python,
)

POSIX_PLATFORMS = ["darwin", "linux", "freebsd14"]


@pytest.mark.parametrize("platform", POSIX_PLATFORMS)
def test_native_python_is_bin_python_on_posix(tmp_path, platform):
    assert native_python(tmp_path / "env", platform) == tmp_path / "env" / "bin" / "python"


def test_native_python_is_scripts_python_exe_on_windows(tmp_path):
    assert native_python(tmp_path / "env", "win32") == tmp_path / "env" / "Scripts" / "python.exe"


@pytest.mark.parametrize("platform", POSIX_PLATFORMS + ["win32"])
def test_portable_python_is_bin_python_on_every_platform(tmp_path, platform):
    """The spelling `.mcp.json` and the skills use — identical on every OS,
    extensionless on purpose (F4)."""
    assert portable_python(tmp_path / "env") == tmp_path / "env" / "bin" / "python"


def test_native_python_defaults_to_the_running_platform(tmp_path):
    expected = "Scripts" if sys.platform == "win32" else "bin"
    assert native_python(tmp_path / "env").parent.name == expected


def test_native_python_accepts_a_path_with_spaces_and_backslashes_as_str(tmp_path):
    env_dir = tmp_path / "my project" / ".hyperspace" / "env"
    as_str = str(env_dir)
    assert native_python(as_str, "win32") == env_dir / "Scripts" / "python.exe"
    assert native_python(as_str, "linux") == env_dir / "bin" / "python"


# ── find_venv_python: whichever layout exists on disk ───────────────────────


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def test_find_venv_python_prefers_posix_python3(tmp_path):
    _touch(tmp_path / ".venv" / "bin" / "python")
    py3 = _touch(tmp_path / ".venv" / "bin" / "python3")
    assert find_venv_python(tmp_path / ".venv") == py3


def test_find_venv_python_finds_the_windows_layout(tmp_path):
    exe = _touch(tmp_path / ".venv" / "Scripts" / "python.exe")
    assert find_venv_python(tmp_path / ".venv") == exe


def test_find_venv_python_none_when_no_interpreter(tmp_path):
    (tmp_path / ".venv").mkdir()
    assert find_venv_python(tmp_path / ".venv") is None


# ── link_bin_to_scripts: the Windows junction, idempotent, never on POSIX ──


@pytest.mark.parametrize("platform", POSIX_PLATFORMS)
def test_link_is_a_no_op_on_posix(tmp_path, platform):
    calls: list = []
    ok, message = link_bin_to_scripts(tmp_path / "env", platform, create_junction=lambda *a: calls.append(a))
    assert ok is True
    assert calls == []
    assert "not needed" in message


def test_link_creates_bin_junction_to_scripts_on_windows(tmp_path):
    env_dir = tmp_path / "env"
    _touch(env_dir / "Scripts" / "python.exe")
    calls: list = []

    def fake_junction(target: str, link: str) -> None:
        calls.append((target, link))
        Path(link).mkdir()
        (Path(link) / "python.exe").write_text("", encoding="utf-8")

    ok, message = link_bin_to_scripts(env_dir, "win32", create_junction=fake_junction)
    assert ok is True, message
    assert calls == [(str(env_dir / "Scripts"), str(env_dir / "bin"))]


def test_link_is_idempotent_when_bin_already_reaches_the_interpreter(tmp_path):
    env_dir = tmp_path / "env"
    _touch(env_dir / "Scripts" / "python.exe")
    _touch(env_dir / "bin" / "python.exe")
    calls: list = []
    ok, message = link_bin_to_scripts(env_dir, "win32", create_junction=lambda *a: calls.append(a))
    assert ok is True, message
    assert calls == []


def test_link_refuses_without_the_native_interpreter(tmp_path):
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    ok, message = link_bin_to_scripts(env_dir, "win32", create_junction=lambda *a: None)
    assert ok is False
    assert "python.exe" in message


def test_link_reports_a_junction_failure_without_raising(tmp_path):
    env_dir = tmp_path / "env"
    _touch(env_dir / "Scripts" / "python.exe")

    def failing_junction(target: str, link: str) -> None:
        raise OSError("volume does not support junctions")

    ok, message = link_bin_to_scripts(env_dir, "win32", create_junction=failing_junction)
    assert ok is False
    assert "volume does not support junctions" in message


@pytest.mark.skipif(sys.platform != "win32", reason="a real NTFS directory junction exists only on Windows")
def test_real_junction_on_windows(tmp_path):
    env_dir = tmp_path / "with space" / "env"
    _touch(env_dir / "Scripts" / "python.exe")
    ok, message = link_bin_to_scripts(env_dir)
    assert ok is True, message
    assert (env_dir / "bin" / "python.exe").is_file()
    # A second run finds the junction already in place and leaves it alone.
    ok_again, _ = link_bin_to_scripts(env_dir)
    assert ok_again is True
