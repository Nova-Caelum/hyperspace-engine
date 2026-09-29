"""v0.1.3 — every command-line entry point writes UTF-8, whatever the pipe's
default encoding.

On Windows a piped stdout/stderr defaults to the ANSI code page (cp1252):
`—` goes out as byte 0x97, and `→` / `✔` cannot be encoded at all, so the
command crashes with UnicodeEncodeError. Claude Code reads a skill command's
output as UTF-8. `PYTHONIOENCODING=cp1252` reproduces that pipe on any OS;
each entry point must override it and emit strict UTF-8.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANSI_PIPE = {**os.environ, "PYTHONIOENCODING": "cp1252"}


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, cwd=str(cwd), env=ANSI_PIPE, capture_output=True, timeout=60)


def _loop_state(*args: str, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return _run([sys.executable, str(ROOT / "bin" / "loop_state.py"), *args], cwd)


def test_loop_state_stdout_is_utf8_on_an_ansi_pipe(tmp_path):
    (tmp_path / "input.md").write_text("Build it.\n", encoding="utf-8")
    init = _loop_state("init", "--goal", "enc-goal", "--input", str(tmp_path / "input.md"),
                       "--workspace", str(tmp_path / "runs"), cwd=tmp_path)
    assert init.returncode == 0, init.stderr
    state = tmp_path / "runs" / "enc-goal" / "loop.state.json"
    for _ in range(2):
        assert _loop_state("bump", str(state), "--event", "startup", cwd=tmp_path).returncode == 0
    notify = _loop_state("notify", str(state), cwd=tmp_path)
    assert notify.returncode == 0, notify.stderr
    assert "soft cap crossed — notify-only" in notify.stdout.decode("utf-8")


def test_loop_state_stderr_refusal_is_utf8_on_an_ansi_pipe(tmp_path):
    (tmp_path / "input.md").write_text("Build it.\n", encoding="utf-8")
    _loop_state("init", "--goal", "enc-goal", "--input", str(tmp_path / "input.md"),
                "--workspace", str(tmp_path / "runs"), cwd=tmp_path)
    state = tmp_path / "runs" / "enc-goal" / "loop.state.json"
    refused = _loop_state("gate-pass", str(state), "--node", "live", "--by", "t", cwd=tmp_path)
    assert refused.returncode == 2  # usage, unchanged
    assert "no exit check is registered for it —" in refused.stderr.decode("utf-8")


def test_hyperspace_cli_is_utf8_on_an_ansi_pipe(tmp_path):
    cli = [sys.executable, "-m", "hyperspace.cli"]
    assert _run([*cli, "init", "--dir", str(tmp_path)], ROOT).returncode == 0
    summary = "arrow → dash — check ✔"
    appended = _run([*cli, "worklog", "append", "--dir", str(tmp_path), "--author", "t",
                     "--project", "p", "--summary", summary], ROOT)
    assert appended.returncode == 0, appended.stderr.decode("utf-8", "replace")
    assert summary in appended.stdout.decode("utf-8")


def test_setup_bootstrap_is_utf8_on_an_ansi_pipe(tmp_path):
    project = tmp_path / "projet é"
    project.mkdir()
    proc = _run([sys.executable, str(ROOT / "bin" / "hyperspace_setup.py"), "--dir", str(project)], tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "projet é" in proc.stdout.decode("utf-8")
