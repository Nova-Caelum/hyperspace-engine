"""T5.1 — the setup skill's provisioning code (hyperspace/setup/provision.py)
and the `hyperspace doctor` CLI entry.

Covers: (a) `provision()` chooses `uv` vs stdlib `venv` and records which;
(b) `check_python` refuses < 3.11, naming the requirement; (c) `select_judge`
under four probe combinations — no key/no CLI, a key present, a working
`claude-code`, and a `claude` present-but-unresponsive fallback; (d)
`write_launcher` writes the right file per platform, executable where it
should be, with the right exec line; (e) `hyperspace doctor` reports one
OK/FAIL line per check and exits 0 only when every check is OK; (f) the
non-interactive CLI path (`hyperspace init --provision --judge none ...`)
performs steps 1-5 without prompting; (g) `python3 -m hyperspace.setup`'s own
import chain has none of this project's PyPI dependencies on it — the
bootstrap entrypoint the skill's step 2 runs BEFORE `.hyperspace/env`
exists, verified against a genuinely dependency-free interpreter rather than
assumed.

Every external boundary — `uv`/`venv`/`pip` subprocesses, `claude`/`codex`
presence and probing — is a FAKE `which`/`run` callable here. No real `uv`,
`claude`, `codex`, or network call anywhere in this file.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hyperspace import cli
from hyperspace.config import load_config
from hyperspace.setup.provision import (
    check_python,
    doctor,
    probe_judges,
    provision,
    provision_env,
    select_judge,
    write_launcher,
)


# ── fakes ─────────────────────────────────────────────────────────────────


def _fake_which(present: set[str]):
    def _which(binary: str) -> str | None:
        return f"/fake/bin/{binary}" if binary in present else None
    return _which


def _fake_run_ok(record: list):
    def _run(argv, **kwargs):
        record.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return _run


def _fake_run_fail(record: list):
    def _run(argv, **kwargs):
        record.append(list(argv))
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")
    return _run


# ── (a) provision_env / provision: uv vs venv, recorded ──────────────────


def test_provision_env_uses_uv_when_on_path(tmp_path):
    record: list = []
    result = provision_env(
        tmp_path, prefer_uv=True, run=_fake_run_ok(record), which=_fake_which({"uv"}),
    )
    assert result["tool"] == "uv"
    assert result["ok"] is True
    assert record[0][:2] == ["uv", "venv"]
    assert record[1][:3] == ["uv", "pip", "install"]


def test_provision_env_falls_back_to_venv_without_uv(tmp_path):
    record: list = []
    result = provision_env(
        tmp_path, prefer_uv=True, run=_fake_run_ok(record), which=_fake_which(set()),
    )
    assert result["tool"] == "venv"
    assert result["ok"] is True
    assert record[0][1:3] == ["-m", "venv"]
    assert record[1][1:3] == ["-m", "pip"]


def test_provision_env_records_failure_without_raising(tmp_path):
    record: list = []
    result = provision_env(
        tmp_path, prefer_uv=True, run=_fake_run_fail(record), which=_fake_which({"uv"}),
    )
    assert result["ok"] is False
    assert result["steps"][0]["exit_code"] == 1


def test_provision_chooses_uv_and_records_which(tmp_path):
    record: list = []
    result = provision(
        tmp_path, judge="none", run=_fake_run_ok(record), which=_fake_which({"uv"}),
        platform="darwin",
    )
    assert result["env"]["tool"] == "uv"
    assert result["python"]["ok"] is True


def test_provision_chooses_venv_and_records_which(tmp_path):
    record: list = []
    result = provision(
        tmp_path, judge="none", run=_fake_run_ok(record), which=_fake_which(set()),
        platform="darwin",
    )
    assert result["env"]["tool"] == "venv"


# ── (b) Python version check ──────────────────────────────────────────────


def test_check_python_refuses_below_3_11_naming_requirement():
    ok, message = check_python(version_info=(3, 10, 4))
    assert ok is False
    assert "3.11" in message
    assert "3.10.4" in message


def test_check_python_accepts_3_11_and_above():
    ok, message = check_python(version_info=(3, 11, 0))
    assert ok is True
    ok, _ = check_python(version_info=(3, 12, 5))
    assert ok is True


# ── (c) select_judge under four probe combinations ────────────────────────


def test_select_judge_none_when_nothing_detected_names_what_was_missing():
    probes = probe_judges({}, which=_fake_which(set()), run=_fake_run_ok([]))
    judge, message = select_judge(probes)
    assert judge == "none"
    assert message is not None
    assert "OPENROUTER_API_KEY" in message
    assert "ANTHROPIC_API_KEY" in message
    assert "claude" in message and "codex" in message


def test_select_judge_anthropic_when_key_present():
    probes = probe_judges(
        {"ANTHROPIC_API_KEY": "sk-fake-not-a-real-key"},
        which=_fake_which(set()), run=_fake_run_ok([]),
    )
    judge, message = select_judge(probes)
    assert judge == "anthropic"
    assert message is None


def test_select_judge_claude_code_when_claude_present_and_ping_succeeds():
    def _run(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout='{"result": "pong"}', stderr="")

    probes = probe_judges({}, which=_fake_which({"claude"}), run=_run)
    judge, message = select_judge(probes)
    assert judge == "claude-code"
    assert message is None


def test_select_judge_none_when_claude_present_but_ping_fails():
    def _run(argv, **kwargs):
        if argv[:2] == ["claude", "-p"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="OAuth session expired")
        return SimpleNamespace(returncode=0, stdout="2.1.251", stderr="")

    probes = probe_judges({}, which=_fake_which({"claude"}), run=_run)
    judge, message = select_judge(probes)
    assert judge == "none"
    assert message is not None
    assert "npm install -g @anthropic-ai/claude-code" in message
    assert "logged in" in message or "log in" in message.lower()


def test_probe_judges_never_puts_key_values_in_the_probe_dict():
    probes = probe_judges(
        {"OPENROUTER_API_KEY": "sk-super-secret-value", "ANTHROPIC_API_KEY": "sk-also-secret"},
        which=_fake_which(set()), run=_fake_run_ok([]),
    )
    dumped = repr(probes)
    assert "sk-super-secret-value" not in dumped
    assert "sk-also-secret" not in dumped
    assert probes["openrouter_key"] is True
    assert probes["anthropic_key"] is True


# ── (d) write_launcher per platform ───────────────────────────────────────


def test_write_launcher_darwin(tmp_path):
    path = write_launcher(tmp_path, "darwin")
    assert path == tmp_path / ".hyperspace" / "Open Hyperspace.command"
    assert path.is_file()
    text = path.read_text()
    assert text.startswith("#!/bin/sh")
    assert "cd " in text
    assert "exec .hyperspace/env/bin/hyperspace serve --open" in text
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & stat.S_IXUSR


def test_write_launcher_windows(tmp_path):
    path = write_launcher(tmp_path, "win32")
    assert path == tmp_path / ".hyperspace" / "Open Hyperspace.bat"
    assert path.is_file()


def test_write_launcher_linux(tmp_path):
    path = write_launcher(tmp_path, "linux")
    assert path == tmp_path / ".hyperspace" / "open-hyperspace.sh"
    assert path.is_file()
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & stat.S_IXUSR


# ── (e) hyperspace doctor ─────────────────────────────────────────────────


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_doctor_all_ok(tmp_path):
    from hyperspace.store import Store

    hyperspace_dir = tmp_path / ".hyperspace"
    (hyperspace_dir / "env" / "bin").mkdir(parents=True)
    (hyperspace_dir / "env" / "bin" / "python").write_text("fake\n")
    Store.init(hyperspace_dir / "graph.db").close()
    port = _free_port()
    (hyperspace_dir / "config.toml").write_text(f'judge = "none"\nport = {port}\nuser = "user"\n')

    ok, lines = doctor(tmp_path)
    assert ok is True
    assert all(line.startswith("OK") for line in lines)
    assert len(lines) == 5


def test_doctor_fails_when_env_missing(tmp_path):
    from hyperspace.store import Store

    hyperspace_dir = tmp_path / ".hyperspace"
    hyperspace_dir.mkdir()
    Store.init(hyperspace_dir / "graph.db").close()
    port = _free_port()
    (hyperspace_dir / "config.toml").write_text(f'judge = "none"\nport = {port}\nuser = "user"\n')

    ok, lines = doctor(tmp_path)
    assert ok is False
    env_lines = [line for line in lines if line.split(":")[0].endswith("env")]
    assert env_lines and env_lines[0].startswith("FAIL")


def test_doctor_recognizes_its_own_door_as_ok(tmp_path):
    from hyperspace.http.server import start
    from hyperspace.store import Store

    hyperspace_dir = tmp_path / ".hyperspace"
    (hyperspace_dir / "env" / "bin").mkdir(parents=True)
    (hyperspace_dir / "env" / "bin" / "python").write_text("fake\n")
    db_path = hyperspace_dir / "graph.db"
    Store.init(db_path).close()

    door = start(db_path, port=0)
    try:
        bound_port = door.server_address[1]
        (hyperspace_dir / "config.toml").write_text(f'judge = "none"\nport = {bound_port}\nuser = "user"\n')
        ok, lines = doctor(tmp_path)
    finally:
        door.shutdown()
        door.server_close()

    assert ok is True
    door_lines = [line for line in lines if line.split(":")[0].endswith("door")]
    assert door_lines and door_lines[0].startswith("OK")
    assert "our own door" in door_lines[0]


# ── (f) non-interactive CLI path ──────────────────────────────────────────


def test_cli_init_provision_non_interactive(tmp_path, monkeypatch, capsys):
    calls: list = []

    def _fake_run(argv, **kwargs):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr("shutil.which", lambda binary: "/fake/bin/uv" if binary == "uv" else None)

    rc = cli.main([
        "init", "--dir", str(tmp_path),
        "--judge", "none", "--port", "8791", "--user", "user", "--provision",
    ])
    out = capsys.readouterr().out

    assert rc == 0
    assert (tmp_path / ".hyperspace" / "graph.db").is_file()
    cfg = load_config(tmp_path)
    assert cfg.judge == "none"
    assert cfg.port == 8791
    assert cfg.user == "user"
    assert (tmp_path / ".hyperspace" / "env").exists() or any(
        c[:2] == ["uv", "venv"] for c in calls
    )
    assert "judge = none" in out


def test_cli_init_provision_rejects_unknown_judge(tmp_path):
    rc = cli.main(["init", "--dir", str(tmp_path), "--provision", "--judge", "bogus"])
    assert rc == 2


def test_cli_unknown_subcommand_names_doctor(capsys):
    rc = cli.main(["nonexistent"])
    assert rc == 2
    combined = "".join(capsys.readouterr())
    assert "doctor" in combined


def test_cli_doctor_subcommand_registered(tmp_path, capsys):
    rc = cli.main(["doctor", "--dir", str(tmp_path)])
    assert rc == 1  # fresh dir: nothing provisioned yet
    out = capsys.readouterr().out
    assert "python" in out
    assert "env" in out


# ── (g) bootstrap entrypoint has no PyPI dependency on its import chain ──

ROOT = Path(__file__).resolve().parents[1]


def test_hyperspace_setup_imports_with_zero_third_party_dependencies(tmp_path):
    """`python3 -m hyperspace.setup` is what the skill's step 2 runs BEFORE
    `.hyperspace/env` exists — nothing this project depends on (pydantic,
    mcp, etc.) is installed anywhere at that moment. A `--without-pip` venv
    has stdlib only, guaranteed, regardless of what's on the host running
    this test suite — so importing successfully against IT is real evidence,
    not an assumption about what happens to be on PATH."""
    bare_python = tmp_path / "bare"
    create = subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(bare_python)],
        capture_output=True, text=True,
    )
    assert create.returncode == 0, create.stderr

    proc = subprocess.run(
        [str(bare_python / "bin" / "python3"), "-c", "import hyperspace.setup.provision"],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert proc.returncode == 0, proc.stderr

    help_proc = subprocess.run(
        [str(bare_python / "bin" / "python3"), "-m", "hyperspace.setup", "--help"],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert help_proc.returncode == 0, help_proc.stderr
    assert "--provision" in help_proc.stdout
