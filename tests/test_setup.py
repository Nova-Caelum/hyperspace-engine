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
from hyperspace.venv_paths import native_python
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
        tmp_path, prefer_uv=True, run=_fake_run_ok(record), which=_fake_which({"uv"}), platform="linux",
    )
    assert result["tool"] == "uv"
    assert result["ok"] is True
    assert record[0][:2] == ["uv", "venv"]
    assert record[1][:3] == ["uv", "pip", "install"]


def test_provision_env_uv_venv_pins_the_interpreter_that_passed_the_check(tmp_path):
    """`check_python` vets `sys.executable`; the env must be built from that
    same interpreter, not whatever `uv` discovers first (a uv-only machine runs
    setup under `uv run --python ">=3.11"`, and PATH may hold an older one)."""
    record: list = []
    provision_env(tmp_path, prefer_uv=True, run=_fake_run_ok(record), which=_fake_which({"uv"}),
                  platform="linux")
    assert record[0][:2] == ["uv", "venv"]
    assert record[0][record[0].index("--python") + 1] == sys.executable


@pytest.mark.parametrize("prefer_uv, present", [(True, {"uv"}), (False, set())])
def test_provision_env_installs_with_the_windows_interpreter_and_links_bin(tmp_path, prefer_uv, present):
    record: list = []
    links: list = []

    def fake_link(env_dir, platform):
        links.append((Path(env_dir), platform))
        return True, "junction ok"

    result = provision_env(
        tmp_path, prefer_uv=prefer_uv, run=_fake_run_ok(record), which=_fake_which(present),
        platform="win32", link=fake_link,
    )
    native = str(tmp_path / ".hyperspace" / "env" / "Scripts" / "python.exe")
    install = record[1]
    assert native in install, install
    assert str(tmp_path / ".hyperspace" / "env" / "bin" / "python") not in install
    assert links == [(tmp_path / ".hyperspace" / "env", "win32")]
    assert result["steps"][-1] == {"command": "link env/bin -> env/Scripts", "exit_code": 0, "message": "junction ok"}
    assert result["ok"] is True


def test_provision_env_fails_when_the_windows_link_fails(tmp_path):
    result = provision_env(
        tmp_path, prefer_uv=True, run=_fake_run_ok([]), which=_fake_which({"uv"}),
        platform="win32", link=lambda env_dir, platform: (False, "volume does not support junctions"),
    )
    assert result["ok"] is False
    assert result["steps"][-1]["exit_code"] == 1
    assert "junctions" in result["steps"][-1]["message"]


def test_provision_env_never_links_on_posix(tmp_path):
    links: list = []
    result = provision_env(
        tmp_path, prefer_uv=True, run=_fake_run_ok([]), which=_fake_which({"uv"}),
        platform="darwin", link=lambda env_dir, platform: links.append(platform) or (True, ""),
    )
    assert result["ok"] is True
    assert links == []
    assert all(step["command"] != "link env/bin -> env/Scripts" for step in result["steps"])


def test_provision_env_falls_back_to_venv_without_uv(tmp_path):
    record: list = []
    result = provision_env(
        tmp_path, prefer_uv=True, run=_fake_run_ok(record), which=_fake_which(set()), platform="linux",
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
        if argv[:2] == ["/fake/bin/claude", "-p"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="OAuth session expired")
        return SimpleNamespace(returncode=0, stdout="2.1.251", stderr="")

    probes = probe_judges({}, which=_fake_which({"claude"}), run=_run)
    judge, message = select_judge(probes)
    assert judge == "none"
    assert message is not None
    assert "npm install -g @anthropic-ai/claude-code" in message
    assert "logged in" in message or "log in" in message.lower()


def test_probe_judges_runs_the_resolved_path_not_the_bare_name():
    """On Windows an npm-installed `claude`/`codex` is a `.cmd` shim:
    `which` finds it via PATHEXT, CreateProcess cannot find it by bare name."""
    seen: list = []

    def _run(argv, **kwargs):
        seen.append(argv[0])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    shims = {b: f"C:/npm/{b}.cmd" for b in ("claude", "codex")}
    probe_judges({}, which=lambda b: shims.get(b), run=_run)
    assert seen and set(seen) == {"C:/npm/claude.cmd", "C:/npm/codex.cmd"}


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


def _assert_executable_on_posix(path: Path) -> None:
    """The POSIX launchers are chmod +x. Only checkable where the bit exists:
    NTFS has none (Python reports it from the extension), and these launchers
    are only ever written for macOS/Linux, where it is checked."""
    if sys.platform == "win32":
        return
    assert stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR


def test_write_launcher_darwin(tmp_path):
    path = write_launcher(tmp_path, "darwin")
    assert path == tmp_path / ".hyperspace" / "Open Hyperspace.command"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh")
    assert "cd " in text
    assert "exec .hyperspace/env/bin/hyperspace serve --open" in text
    _assert_executable_on_posix(path)


def test_write_launcher_windows(tmp_path):
    path = write_launcher(tmp_path, "win32")
    assert path == tmp_path / ".hyperspace" / "Open Hyperspace.bat"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert 'cd /d "%~dp0.."' in text
    assert 'if not exist ".hyperspace\\env\\Scripts\\hyperspace.exe"' in text
    assert "hyperspace-setup" in text
    assert "exit /b 1" in text
    assert '".hyperspace\\env\\Scripts\\hyperspace.exe" serve --open' in text
    assert "Untested" not in text


def test_write_launcher_linux(tmp_path):
    path = write_launcher(tmp_path, "linux")
    assert path == tmp_path / ".hyperspace" / "open-hyperspace.sh"
    assert path.is_file()
    _assert_executable_on_posix(path)


# ── (e) hyperspace doctor ─────────────────────────────────────────────────


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _fake_env(hyperspace_dir: Path, platform: str = sys.platform, *, linked: bool = True) -> None:
    """The interpreter file(s) `doctor` looks for, in `platform`'s layout —
    `bin/python` on POSIX; `Scripts/python.exe` plus (when `linked`) the
    `bin/python.exe` the junction exposes, on Windows."""
    env_dir = hyperspace_dir / "env"
    if platform == "win32":
        (env_dir / "Scripts").mkdir(parents=True, exist_ok=True)
        (env_dir / "Scripts" / "python.exe").write_text("fake\n", encoding="utf-8")
        if linked:
            (env_dir / "bin").mkdir(parents=True, exist_ok=True)
            (env_dir / "bin" / "python.exe").write_text("fake\n", encoding="utf-8")
    else:
        (env_dir / "bin").mkdir(parents=True, exist_ok=True)
        (env_dir / "bin" / "python").write_text("fake\n", encoding="utf-8")


def test_doctor_all_ok(tmp_path):
    from hyperspace.store import Store

    hyperspace_dir = tmp_path / ".hyperspace"
    _fake_env(hyperspace_dir)
    Store.init(hyperspace_dir / "graph.db").close()
    port = _free_port()
    (hyperspace_dir / "config.toml").write_text(f'judge = "none"\nport = {port}\nuser = "user"\n', encoding="utf-8")

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
    (hyperspace_dir / "config.toml").write_text(f'judge = "none"\nport = {port}\nuser = "user"\n', encoding="utf-8")

    ok, lines = doctor(tmp_path)
    assert ok is False
    env_lines = [line for line in lines if line.split(":")[0].endswith("env")]
    assert env_lines and env_lines[0].startswith("FAIL")


def _doctor_env_line(tmp_path, platform, *, linked=True):
    from hyperspace.store import Store

    hyperspace_dir = tmp_path / ".hyperspace"
    _fake_env(hyperspace_dir, platform, linked=linked)
    Store.init(hyperspace_dir / "graph.db").close()
    (hyperspace_dir / "config.toml").write_text(f'judge = "none"\nport = {_free_port()}\nuser = "user"\n', encoding="utf-8")
    _ok, lines = doctor(tmp_path, platform=platform)
    return next(line for line in lines if line.split(":")[0].endswith("env"))


def test_doctor_windows_layout_ok_names_the_native_interpreter(tmp_path):
    line = _doctor_env_line(tmp_path, "win32")
    assert line.startswith("OK"), line
    assert "Scripts" in line and "python.exe" in line


def test_doctor_windows_fails_when_bin_does_not_reach_the_interpreter(tmp_path):
    """`.mcp.json` and every skill run `.hyperspace/env/bin/python`; on
    Windows that needs the junction — a venv without it cannot start the MCP
    server, so doctor must not call it OK."""
    line = _doctor_env_line(tmp_path, "win32", linked=False)
    assert line.startswith("FAIL"), line
    assert "env/bin" in line
    assert "hyperspace-setup" in line


def test_doctor_posix_layout_on_a_windows_check_is_missing(tmp_path):
    from hyperspace.store import Store

    hyperspace_dir = tmp_path / ".hyperspace"
    _fake_env(hyperspace_dir, "linux")
    Store.init(hyperspace_dir / "graph.db").close()
    _ok, lines = doctor(tmp_path, platform="win32")
    env_line = next(line for line in lines if line.split(":")[0].endswith("env"))
    assert env_line.startswith("FAIL")


def test_doctor_recognizes_its_own_door_as_ok(tmp_path):
    from hyperspace.http.server import start
    from hyperspace.store import Store

    hyperspace_dir = tmp_path / ".hyperspace"
    _fake_env(hyperspace_dir)
    db_path = hyperspace_dir / "graph.db"
    Store.init(db_path).close()

    door = start(db_path, port=0)
    try:
        bound_port = door.server_address[1]
        (hyperspace_dir / "config.toml").write_text(f'judge = "none"\nport = {bound_port}\nuser = "user"\n', encoding="utf-8")
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
        capture_output=True, encoding="utf-8", errors="replace",
    )
    assert create.returncode == 0, create.stderr

    bare_interpreter = str(native_python(bare_python))
    proc = subprocess.run(
        [bare_interpreter, "-c", "import hyperspace.setup.provision"],
        capture_output=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert proc.returncode == 0, proc.stderr

    help_proc = subprocess.run(
        [bare_interpreter, "-m", "hyperspace.setup", "--help"],
        capture_output=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert help_proc.returncode == 0, help_proc.stderr
    assert "--provision" in help_proc.stdout


def test_bootstrap_script_runs_on_a_bare_interpreter_without_pythonpath(tmp_path):
    """The setup skill's step 2 is `<python> "${CLAUDE_PLUGIN_ROOT}/bin/hyperspace_setup.py" …`
    — one form that parses the same in sh, Git Bash, PowerShell and cmd (the
    old `PYTHONPATH="…" python3 -m hyperspace.setup` was sh-only syntax). The
    script must find the plugin's own `hyperspace` package by itself: no
    PYTHONPATH, no dependencies, a stdlib-only interpreter."""
    bare_python = tmp_path / "bare env"
    create = subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(bare_python)],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    assert create.returncode == 0, create.stderr
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [str(native_python(bare_python)), str(ROOT / "bin" / "hyperspace_setup.py"), "--help"],
        capture_output=True, encoding="utf-8", errors="replace", env=env, cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    assert "--provision" in proc.stdout
    assert "hyperspace_setup.py" in proc.stdout


def test_bootstrap_script_initialises_the_store(tmp_path):
    project = tmp_path / "my project"
    project.mkdir()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "hyperspace_setup.py"), "--dir", str(project)],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    assert (project / ".hyperspace" / "graph.db").is_file()
