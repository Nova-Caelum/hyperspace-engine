"""tests/test_provenance.py — the project's `.hyperspace/env` is started only
through `hyperspace/provenance.py`, and setup records every env it builds.

Threat: a downloaded or cloned folder can ship a file at
`.hyperspace/env/bin/python` (or `Scripts/python.exe`). Until 1.0.3 the
plugin's `.mcp.json` started that file directly, in every folder the plugin
was enabled in. Now `.mcp.json` starts `bin/hyperspace-env`, which hands the
computer's own Python to `provenance.py run`, and that starts the env only
when it matches the record setup wrote OUTSIDE the project, in
`~/.hyperspace/envs.json`.

Covers: (a) the server command from `.mcp.json`, started as Claude Code
starts it, never runs a folder's own interpreter — unrecorded, or swapped in
after setup recorded the real one — and exits 3 with one line; (b) a
recorded env starts, and setup (`provision_env`) records what it builds, so
the same command answers an MCP `initialize`; (c) a rebuild replaces the env
and never deletes through a link; (d) `provenance` itself: each field it
compares, its exit codes and its one-line refusal.

Every test points HOME and USERPROFILE at a scratch folder, so nothing here
reads or writes the real `~/.hyperspace/envs.json`.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import subprocess
import sys
import sysconfig
from pathlib import Path
from types import SimpleNamespace

import pytest

from hyperspace import provenance
from hyperspace.setup.provision import provision_env
from hyperspace.venv_paths import _create_junction, link_bin_to_scripts
from probes._mcp_launch import mcp_launch

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = ROOT / "hyperspace" / "provenance.py"
WINDOWS = sys.platform == "win32"
TIMEOUT = 120


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return path


# ── helpers ───────────────────────────────────────────────────────────────


def _env(project: Path) -> Path:
    return project / ".hyperspace" / "env"


def _marker_lines(marker: Path) -> int:
    return marker.read_text(encoding="utf-8").count("\n") if marker.exists() else 0


def _plant_fake_env(project: Path, marker: Path) -> Path:
    """What a downloaded folder can carry: an interpreter at every spelling a
    launcher might start, each appending a line to `marker` when it runs.

    POSIX: `sh` scripts at `bin/python`, `bin/python.exe` and
    `Scripts/python.exe`, plus a `pyvenv.cfg`. Windows will only start a real
    `.exe`, so there it is a real venv whose `site-packages` carries a `.pth`
    line that writes the marker as the interpreter starts — the env's
    `site-packages` is attacker input as much as its interpreter is."""
    env = _env(project)
    if WINDOWS:
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(env)], check=True, capture_output=True)
        line = f"import os; open({str(marker)!r}, 'a').write('started\\n')\n"
        (env / "Lib" / "site-packages" / "zz_marker.pth").write_text(line, encoding="utf-8")
        (env / "bin").mkdir()
        shutil.copy2(env / "Scripts" / "python.exe", env / "bin" / "python.exe")
    else:
        for rel in ("bin/python", "bin/python.exe", "Scripts/python.exe"):
            path = env / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'#!/bin/sh\necho "$0 $*" >> "{marker}"\n', encoding="utf-8")
            path.chmod(0o755)
        (env / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.11.0\n", encoding="utf-8")
    return env


def _assert_the_fake_is_live(env: Path, marker: Path) -> None:
    """Control: started directly, the planted interpreter does write the
    marker. Without this, "written zero times" could mean a fake that never
    worked."""
    subprocess.run([provenance.interpreter(str(env)), "-c", "pass"], capture_output=True, timeout=TIMEOUT)
    # >= 1: on Windows the venv's python.exe is a launcher, and the .pth line can run in both processes.
    assert _marker_lines(marker) >= 1, "the planted interpreter did not write its marker when started directly"
    marker.unlink()


def _real_env(project: Path) -> Path:
    """A real venv of this OS's layout, linked as provisioning links it."""
    env = _env(project)
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(env)], check=True, capture_output=True)
    ok, message = link_bin_to_scripts(env)
    assert ok, message
    return env


def _recordable_env(project: Path) -> Path:
    """The smallest folder `provenance` will record: a `pyvenv.cfg` and an
    interpreter in this OS's layout. POSIX: `bin/python` links to an
    interpreter outside the env, as a venv's does. Windows: a file inside it."""
    env = _env(project)
    python = Path(provenance.interpreter(str(env)))
    python.parent.mkdir(parents=True)
    (env / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.11.0\n", encoding="utf-8")
    if WINDOWS:
        python.write_bytes(b"MZ not really an interpreter")
    else:
        python.symlink_to(sys.executable)
    return env


def _swap_in_a_copy(env: Path) -> None:
    """Replace the env folder with one that looks the same but that setup did
    not leave its token in: a folder swapped in from elsewhere, or the env
    rebuilt without setup (`uv venv --clear` removes the token too)."""
    copy = env.with_name("env.copy")
    shutil.copytree(env, copy, symlinks=True, ignore=shutil.ignore_patterns(provenance.TOKEN_FILE))
    env.rename(env.with_name("env.old"))
    copy.rename(env)


def _server_env(project: Path) -> dict:
    return {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}


def _start_server(project: Path, *, args: list[str] | None = None) -> subprocess.CompletedProcess:
    """`.mcp.json`'s server command, substituted and spawned the way Claude
    Code spawns it: no shell, cwd the project, CLAUDE_PROJECT_DIR set, stdin
    closed."""
    command, mcp_args = mcp_launch(ROOT, project)
    return subprocess.run(
        [command, *(mcp_args if args is None else args)],
        cwd=str(project), env=_server_env(project), stdin=subprocess.DEVNULL,
        capture_output=True, encoding="utf-8", errors="replace", timeout=TIMEOUT,
    )


def _provenance_cli(*args: str, project: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ) if project is None else _server_env(project)
    return subprocess.run(
        [sys.executable, "-I", str(PROVENANCE), *args], env=env, stdin=subprocess.DEVNULL,
        capture_output=True, encoding="utf-8", errors="replace", timeout=TIMEOUT,
    )


def _offline_run(argv, **kwargs):
    """Stands in for the two commands `provision_env` runs on its stdlib path.
    The venv is real (`--without-pip`); "installing this checkout" is a `.pth`
    onto the test interpreter's own site-packages, so the new env imports this
    checkout and its dependencies with no network call."""
    argv = [str(arg) for arg in argv]
    if argv[1:3] == ["-m", "venv"]:
        return subprocess.run(argv[:3] + ["--without-pip"] + argv[3:], capture_output=True, text=True)
    if argv[1:4] == ["-m", "pip", "install"]:
        site = subprocess.run(
            [argv[0], "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert os.path.isabs(site), f"{argv[0]} is not a real interpreter"
        dev_site = sysconfig.get_paths()["purelib"]
        Path(site, "zz_dev.pth").write_text(f"import site; site.addsitedir({dev_site!r})\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    raise AssertionError(f"unexpected command: {argv}")


def _provision(project: Path) -> dict:
    return provision_env(project, prefer_uv=False, run=_offline_run, which=lambda name: None)


def _step(result: dict, prefix: str) -> dict:
    return next(step for step in result["steps"] if step["command"].startswith(prefix))


# ── (a) the server command never runs a folder's own interpreter ─────────


def test_server_command_refuses_an_unrecorded_env_and_starts_nothing(tmp_path):
    project = tmp_path / "downloaded project"
    marker = tmp_path / "started.txt"
    env = _plant_fake_env(project, marker)
    _assert_the_fake_is_live(env, marker)

    proc = _start_server(project)

    assert _marker_lines(marker) == 0, "the folder's own interpreter was started:\n" + marker.read_text(encoding="utf-8")
    assert proc.returncode == provenance.REFUSED, (proc.returncode, proc.stdout, proc.stderr)
    assert proc.stdout == ""
    assert len(proc.stderr.strip().splitlines()) == 1, proc.stderr
    assert "no record" in proc.stderr


def test_server_command_refuses_an_env_swapped_in_after_setup_recorded_one(tmp_path):
    project = tmp_path / "set up project"
    marker = tmp_path / "started.txt"
    env = _plant_fake_env(project, marker)
    provenance.register(str(project), by="test")
    _swap_in_a_copy(env)

    proc = _start_server(project)

    assert _marker_lines(marker) == 0
    assert proc.returncode == provenance.REFUSED, (proc.returncode, proc.stdout, proc.stderr)
    assert proc.stdout == ""
    assert "token" in proc.stderr


def test_server_command_without_an_env_exits_missing_with_one_line(tmp_path):
    project = tmp_path / "never set up"
    project.mkdir()
    proc = _start_server(project)
    assert proc.returncode == provenance.MISSING, (proc.returncode, proc.stdout, proc.stderr)
    assert proc.stdout == ""
    assert len(proc.stderr.strip().splitlines()) == 1, proc.stderr
    assert "hyperspace-setup" in proc.stderr


# ── (b) a recorded env starts; setup records what it builds ──────────────


def test_server_command_starts_a_recorded_env(tmp_path):
    project = tmp_path / "my project"
    env = _real_env(project)
    provenance.register(str(project), by="test")

    proc = _start_server(project, args=["-c", "import sys; print(sys.prefix)"])

    assert proc.returncode == 0, proc.stderr
    assert Path(proc.stdout.strip()).resolve() == env.resolve()


def _initialize(project: Path):
    """One MCP `initialize` against the server `.mcp.json` starts, with the
    project as cwd, as Claude Code starts it."""
    from mcp import StdioServerParameters
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    command, args = mcp_launch(ROOT, project)
    params = StdioServerParameters(command=command, args=args, env=_server_env(project), cwd=str(project))

    async def initialize():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                return await session.initialize()

    return asyncio.run(asyncio.wait_for(initialize(), TIMEOUT))


def test_setup_records_the_env_outside_the_project_and_the_server_answers_initialize(tmp_path, home):
    project = tmp_path / "my project"
    project.mkdir()

    result = _provision(project)

    assert result["ok"] is True, result
    assert _step(result, "record the environment")["exit_code"] == 0
    record = home / ".hyperspace" / "envs.json"
    assert Path(provenance.record_path()) == record
    assert project.resolve() not in record.resolve().parents
    entry = json.loads(record.read_text(encoding="utf-8"))["envs"][os.path.normcase(os.path.realpath(project))]
    assert entry["env"] == os.path.realpath(_env(project))
    assert entry["by"].startswith("hyperspace-engine ")
    assert provenance.verify(str(project))[0] == provenance.OK
    assert _initialize(project).server_info.name == "hyperspace"


def test_server_never_imports_a_hyperspace_package_the_project_ships(tmp_path):
    """`-m hyperspace.mcp` with the project as cwd would put the project first
    on `sys.path`, so a folder's own `hyperspace/__init__.py` would run inside
    a recorded env. `.mcp.json` passes `-P`; the installed package answers."""
    project = tmp_path / "cloned project"
    project.mkdir()
    marker = tmp_path / "shadow.txt"
    (project / "hyperspace").mkdir()
    (project / "hyperspace" / "__init__.py").write_text(
        f"open({str(marker)!r}, 'a').write('imported\\n')\n", encoding="utf-8",
    )
    assert _provision(project)["ok"] is True

    try:
        initialized, error = _initialize(project), None
    except Exception as exc:  # noqa: BLE001 — the marker is asserted first
        initialized, error = None, exc

    assert _marker_lines(marker) == 0, "the project's own hyperspace package was imported by the server"
    assert error is None, repr(error)
    assert initialized.server_info.name == "hyperspace"


def _plant_python_on_path(folder: Path, marker: Path) -> None:
    """A `python3` and a `python` that write the marker when started."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("python3", "python"):
        path = folder / name
        path.write_text(f'#!/bin/sh\necho "$0 $*" >> "{marker}"\nexit 0\n', encoding="utf-8")
        path.chmod(0o755)


@pytest.mark.skipif(WINDOWS, reason="the .cmd's own check runs on the Windows CI job through the server tests")
@pytest.mark.parametrize("path_entry", ["absolute", "relative"])
def test_launcher_skips_a_python_inside_the_project_even_first_on_path(tmp_path, home, path_entry):
    """PATH can lead into the project (an activated env, a relative entry); the
    launcher passes over any Python that lives there and uses the computer's
    own — here the one in `~/.local/bin`, which it always tries."""
    project = tmp_path / "downloaded project"
    marker = tmp_path / "started.txt"
    _plant_python_on_path(project / "tools", marker)
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "python3.11").symlink_to(sys.executable)
    entry = str(project / "tools") if path_entry == "absolute" else "tools"
    command, args = mcp_launch(ROOT, project)

    proc = subprocess.run(
        [command, *args], cwd=str(project), stdin=subprocess.DEVNULL,
        env={**_server_env(project), "PATH": entry + os.pathsep + os.environ.get("PATH", "")},
        capture_output=True, encoding="utf-8", errors="replace", timeout=TIMEOUT,
    )

    assert _marker_lines(marker) == 0, "a Python inside the project was started:\n" + marker.read_text(encoding="utf-8")
    assert proc.returncode == provenance.MISSING, (proc.returncode, proc.stdout, proc.stderr)


def test_setup_ignores_the_env_in_the_projects_gitignore(tmp_path):
    project = tmp_path / "my project"
    project.mkdir()
    (project / ".gitignore").write_text("node_modules/", encoding="utf-8")
    _provision(project)
    _provision(project)
    assert (project / ".gitignore").read_text(encoding="utf-8").splitlines() == ["node_modules/", ".hyperspace/env/"]


# ── (c) a rebuild replaces the env, and never deletes through a link ─────


def test_setup_rebuild_replaces_an_unrecorded_env_instead_of_merging_into_it(tmp_path):
    project = tmp_path / "downloaded project"
    marker = tmp_path / "started.txt"
    _plant_fake_env(project, marker)
    planted = _env(project) / "planted.txt"
    planted.write_text("left by the folder\n", encoding="utf-8")

    result = _provision(project)

    assert result["ok"] is True, result
    assert not planted.exists()
    assert _marker_lines(marker) == 0
    assert provenance.verify(str(project))[0] == provenance.OK


def _link_dir(link: Path, target: Path) -> None:
    if WINDOWS:
        _create_junction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_setup_rebuild_removes_an_env_link_and_never_what_it_points_to(tmp_path):
    victim = tmp_path / "someone else's folder"
    victim.mkdir()
    (victim / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    (victim / "keep.txt").write_text("keep me\n", encoding="utf-8")
    project = tmp_path / "downloaded project"
    (project / ".hyperspace").mkdir(parents=True)
    _link_dir(_env(project), victim)

    result = _provision(project)

    assert result["ok"] is True, result
    assert (victim / "keep.txt").read_text(encoding="utf-8") == "keep me\n"
    assert sorted(path.name for path in victim.iterdir()) == ["keep.txt", "pyvenv.cfg"]
    assert not os.path.islink(_env(project))
    assert os.path.realpath(_env(project)) == os.path.join(os.path.realpath(project), ".hyperspace", "env")


def test_setup_refuses_to_build_when_hyperspace_leads_outside_the_project(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "env").mkdir(parents=True)
    (elsewhere / "env" / "keep.txt").write_text("keep me\n", encoding="utf-8")
    project = tmp_path / "downloaded project"
    project.mkdir()
    _link_dir(project / ".hyperspace", elsewhere)
    calls: list = []

    result = provision_env(project, prefer_uv=False, run=lambda argv, **kw: calls.append(argv), which=lambda n: None)

    assert result["ok"] is False
    assert calls == []
    assert (elsewhere / "env" / "keep.txt").is_file()
    assert "outside the project" in result["steps"][0]["message"]


# ── (d) provenance itself ────────────────────────────────────────────────


def test_check_says_unknown_for_an_unrecorded_env_and_ok_once_registered(tmp_path):
    project = tmp_path / "my project"
    _recordable_env(project)

    unrecorded = _provenance_cli("check", str(project))
    assert (unrecorded.returncode, unrecorded.stdout.strip()) == (provenance.REFUSED, "unknown")

    provenance.register(str(project), by="test")
    recorded = _provenance_cli("check", str(project))
    assert (recorded.returncode, recorded.stdout.strip()) == (provenance.OK, "ok")


def test_check_says_missing_without_an_env(tmp_path):
    project = tmp_path / "empty project"
    project.mkdir()
    proc = _provenance_cli("check", str(project))
    assert (proc.returncode, proc.stdout.strip()) == (provenance.MISSING, "missing")


def test_check_uses_claude_project_dir_when_given_no_folder(tmp_path):
    project = tmp_path / "my project"
    _recordable_env(project)
    provenance.register(str(project), by="test")
    proc = _provenance_cli("check", project=project)
    assert (proc.returncode, proc.stdout.strip()) == (provenance.OK, "ok")


def test_an_env_deleted_and_rebuilt_without_registering_is_refused(tmp_path):
    project = tmp_path / "my project"
    env = _recordable_env(project)
    provenance.register(str(project), by="test")
    _swap_in_a_copy(env)
    status, python, reason = provenance.verify(str(project))
    assert (status, python) == (provenance.REFUSED, None)
    assert "token" in reason


def test_an_edited_pyvenv_cfg_is_refused(tmp_path):
    project = tmp_path / "my project"
    env = _recordable_env(project)
    provenance.register(str(project), by="test")
    with (env / "pyvenv.cfg").open("a", encoding="utf-8") as handle:
        handle.write("include-system-site-packages = true\n")
    status, _python, reason = provenance.verify(str(project))
    assert status == provenance.REFUSED
    assert "pyvenv_cfg_sha256" in reason


def test_a_replaced_interpreter_is_refused(tmp_path):
    """POSIX: `bin/python` links to an interpreter outside the env; a regular
    file put in its place is a different interpreter path. Windows: the
    interpreter is a file inside the env, so its bytes are compared."""
    project = tmp_path / "my project"
    env = _recordable_env(project)
    provenance.register(str(project), by="test")
    python = Path(provenance.interpreter(str(env)))
    python.unlink()
    python.write_bytes(b"#!/bin/sh\necho swapped\n")
    status, _python, reason = provenance.verify(str(project))
    assert status == provenance.REFUSED
    assert ("python_sha256" if WINDOWS else "its python no longer") in reason


def test_a_record_for_another_folder_does_not_cover_this_one(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    _recordable_env(first)
    _recordable_env(second)
    provenance.register(str(first), by="test")
    assert provenance.verify(str(first))[0] == provenance.OK
    assert provenance.verify(str(second))[0] == provenance.REFUSED


def test_run_refused_prints_one_line_to_stderr_and_nothing_to_stdout(tmp_path):
    project = tmp_path / "downloaded project"
    marker = tmp_path / "started.txt"
    _plant_fake_env(project, marker)
    proc = _provenance_cli("run", "--", "-c", "print('ran')", project=project)
    assert proc.returncode == provenance.REFUSED
    assert proc.stdout == ""
    assert len(proc.stderr.strip().splitlines()) == 1, proc.stderr
    assert _marker_lines(marker) == 0


def test_run_starts_a_recorded_env_with_its_arguments(tmp_path):
    project = tmp_path / "my project"
    env = _real_env(project)
    provenance.register(str(project), by="test")
    proc = _provenance_cli("run", "--", "-c", "import sys; print(sys.prefix); sys.exit(7)", project=project)
    assert proc.returncode == 7, proc.stderr
    assert Path(proc.stdout.strip()).resolve() == env.resolve()


def test_register_without_an_env_raises_and_writes_nothing(tmp_path, home):
    project = tmp_path / "empty project"
    project.mkdir()
    with pytest.raises(FileNotFoundError):
        provenance.register(str(project), by="test")
    assert not (home / ".hyperspace").exists()


@pytest.mark.skipif(WINDOWS, reason="POSIX permission bits")
def test_register_writes_the_record_0600_in_a_0700_folder(tmp_path, home):
    project = tmp_path / "my project"
    _recordable_env(project)
    provenance.register(str(project), by="test")
    folder = home / ".hyperspace"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((folder / "envs.json").stat().st_mode) == 0o600
    assert [path.name for path in folder.iterdir()] == ["envs.json"]
