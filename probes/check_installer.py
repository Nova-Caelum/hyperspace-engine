#!/usr/bin/env python3
"""T5.1 verdict check: a fresh-directory, non-interactive dry run of the
hyperspace-setup skill's steps — no key, no `claude`/`codex` on PATH.

Sub-checks, all must PASS:
  (a) the real provisioning (`hyperspace.setup.provision.provision`) with the
      real `uv` creates `.hyperspace/env` — the venv's own interpreter, and
      `.hyperspace/env/bin/python` (the spelling `.mcp.json` runs) reaching it
      on every OS (a junction on Windows)
  (b) `.hyperspace/graph.db` exists (`hyperspace init`'s store step)
  (c) `.hyperspace/config.toml` reads `judge = "none"` and the run captured
      the fallback message that names what was missing
  (d) the launcher for this platform exists (executable on POSIX), and
      RUNNING it — `cmd /c "Open Hyperspace.bat"` on Windows, `sh <launcher>`
      elsewhere — serves the console on the configured port and opens the
      browser at it (a recording fake browser via `BROWSER`); that same
      running door, which is the WHEEL provisioning installed (not the source
      tree), answers `GET /` with the console page: 200, `text/html` — a wheel
      that omits `ui/dist` serves a 404 there; on Windows the same `.bat` in a
      project with no environment refuses (exit 1) naming the
      `hyperspace-setup` skill
  (e) the door starts on a free port and answers `GET /api/projects`, then
      `hyperspace doctor` re-runs the check phase and exits 0
  (f) the running interpreter's own site-packages (`sys.executable -m pip
      list --format=freeze`) is byte-identical before and after — nothing
      this run did touched global/dev packages, only `.hyperspace/env`
      inside the fresh temp project

PATH construction note (found empirically, not assumed): on this Mac `uv`,
`claude` and `codex` are symlinks in the SAME directory (`~/.local/bin`), so
stripping "any PATH entry containing claude or codex" would take `uv` down
with it. This probe instead builds a shim directory holding ONLY a `uv`
(and `uvx`) symlink, backed by the standard system directories with any
directory that itself contains a `claude`/`codex` binary excluded — `which`
on the resulting PATH finds `uv` and never `claude`/`codex`.

Usage: probes/check_installer.py --out <path>
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _proc import stop_tree  # noqa: E402
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hyperspace.config import load_config  # noqa: E402
from hyperspace.http.server import start  # noqa: E402
from hyperspace.setup.provision import doctor, provision  # noqa: E402
from hyperspace.store import Store  # noqa: E402
from hyperspace.venv_paths import native_python, portable_python  # noqa: E402

IS_WINDOWS = sys.platform == "win32"
_HIDDEN_BINARIES = ("claude", "codex", "claude.exe", "codex.exe", "claude.cmd", "codex.cmd")
_SYSTEM_DIRS = (
    [os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32"), os.environ.get("SYSTEMROOT", r"C:\Windows")]
    if IS_WINDOWS else ["/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin"]
)


def _trim(text, limit=4000):
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _dir_has_any(directory: str, names: tuple[str, ...]) -> bool:
    return any((Path(directory) / name).exists() for name in names)


def _build_stripped_path(shim_dir: Path) -> str:
    """A PATH with a real `uv` reachable but no `claude`/`codex` anywhere on
    it — see module docstring for why a naive per-entry strip is unsafe on
    this machine."""
    shim_dir.mkdir(parents=True, exist_ok=True)
    real_uv = shutil.which("uv")
    if real_uv is not None:
        # Windows: a copy (symlinks need a privilege a Windows user may lack);
        # uv is a single self-contained executable, so a copy runs the same.
        place = shutil.copy2 if IS_WINDOWS else (lambda src, dst: Path(dst).symlink_to(src))
        for name in ("uv", "uvx"):
            source = Path(real_uv).with_name(name + Path(real_uv).suffix)
            if source.exists():
                place(str(source), str(shim_dir / source.name))

    safe_system_dirs = [d for d in _SYSTEM_DIRS if Path(d).is_dir() and not _dir_has_any(d, _HIDDEN_BINARIES)]
    return os.pathsep.join([str(shim_dir), *safe_system_dirs])


def _fresh_env(shim_dir: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")}
    env["PATH"] = _build_stripped_path(shim_dir)
    return env


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _fake_browser(directory: Path) -> tuple[Path, Path]:
    """A `BROWSER` executable that records the URL it was asked to open and
    exits 0 — so `serve --open` is observable and no real browser starts.
    Python's `webbrowser` runs `BROWSER` as `[<executable>, <url>]`."""
    directory.mkdir(parents=True, exist_ok=True)
    record = directory / "opened.txt"
    if IS_WINDOWS:
        browser = directory / "browser.bat"
        browser.write_text(f'@echo %~1> "{record}"\r\n@exit /b 0\r\n', encoding="utf-8")
    else:
        browser = directory / "browser"
        browser.write_text(f'#!/bin/sh\nprintf "%s\\n" "$1" > "{record}"\n', encoding="utf-8")
        browser.chmod(0o755)
    return browser, record


def _launcher_argv(launcher: Path) -> list[str]:
    """How a double-click runs it: `cmd` for a `.bat`, `sh` for the POSIX ones."""
    return ["cmd", "/d", "/c", str(launcher)] if launcher.suffix == ".bat" else ["sh", str(launcher)]


def _console_page(port: int) -> dict:
    """`GET /` on the running door. A missing console bundle is a 404, which
    `urlopen` raises as `HTTPError` — an answer to record, not a failure to
    propagate (an `HTTPError` is itself a readable response)."""
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5)
    except urllib.error.HTTPError as exc:
        resp = exc
    except (urllib.error.URLError, OSError) as exc:
        return {"status": None, "content_type": "", "ok": False, "body_head": _trim(str(exc), 200)}
    with resp:
        body = resp.read().decode("utf-8", errors="replace")
        content_type = resp.headers.get("Content-Type", "")
        return {
            "status": resp.status, "content_type": content_type,
            "ok": resp.status == 200 and content_type.startswith("text/html") and "<html" in body.lower(),
            "body_head": _trim(body, 200),
        }


def _run_launcher(launcher: Path, port: int, env: dict, browser: Path, record: Path) -> dict:
    """Runs the launcher, waits up to 60 s for the door on `port`, stops it."""
    proc = subprocess.Popen(
        _launcher_argv(launcher), env={**env, "BROWSER": str(browser)},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    served = False
    console_page = None
    deadline = time.time() + 60
    try:
        while time.time() < deadline and proc.poll() is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/projects", timeout=2) as resp:
                    served = resp.status == 200
                    break
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)
        if served:
            console_page = _console_page(port)
        # `--open` fires right after the bind; give the recorder a moment.
        for _ in range(20):
            if record.is_file():
                break
            time.sleep(0.25)
    finally:
        exited_early = proc.poll()
        stop_tree(proc)
    opened = record.read_text(encoding="utf-8", errors="replace").strip() if record.is_file() else ""
    return {
        "argv": _launcher_argv(launcher),
        "served": served,
        "console_page": console_page,
        "opened_url": opened,
        "opened_ok": opened.rstrip("/") == f"http://127.0.0.1:{port}",
        "exited_before_serving": exited_early,
    }


def _run_launcher_without_env(launcher: Path, tmp_path: Path, env: dict) -> dict:
    """The Windows `.bat` in a project that was never set up: exit 1 and a
    message naming the fix, never a hang or a silent failure."""
    bare = tmp_path / "never set up" / ".hyperspace"
    bare.mkdir(parents=True)
    copy = bare / launcher.name
    shutil.copy2(launcher, copy)
    proc = subprocess.run(
        _launcher_argv(copy), env=env, stdin=subprocess.DEVNULL,
        capture_output=True, encoding="utf-8", errors="replace", timeout=60,
    )
    return {
        "exit_code": proc.returncode,
        "stdout": _trim(proc.stdout),
        "refused_ok": proc.returncode == 1 and "hyperspace-setup" in proc.stdout,
    }


def _pip_freeze(python: str) -> str:
    proc = subprocess.run([python, "-m", "pip", "list", "--format=freeze"], capture_output=True,
                          encoding="utf-8", errors="replace")
    return proc.stdout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    evidence: dict = {}
    started_at = time.time()
    before_freeze = _pip_freeze(sys.executable)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        shim_dir = tmp_path / "shim-bin"
        env = _fresh_env(shim_dir)
        which_fn = lambda binary: shutil.which(binary, path=env.get("PATH"))  # noqa: E731

        def run_fn(argv_, **kwargs):
            kwargs.setdefault("env", env)
            return subprocess.run(argv_, **kwargs)

        evidence["env_probe"] = {
            "which_uv": which_fn("uv"),
            "which_claude": which_fn("claude"),
            "which_codex": which_fn("codex"),
        }

        project_dir = tmp_path / "fresh project"
        project_dir.mkdir()
        db_path = project_dir / ".hyperspace" / "graph.db"
        Store.init(db_path).close()

        # `port=8791` mirrors the brief's own non-interactive example
        # (`hyperspace init --judge none --port 8791 --user user
        # --provision`) — the door's LIVE functional check just below binds
        # its own ephemeral `port=0` instead, so this config value is never
        # actually listened on during the probe.
        port = _free_port()
        provision_result = provision(
            project_dir,
            judge=None, port=port, user="user",
            prefer_uv=True, run=run_fn, which=which_fn, env=env,
            platform=sys.platform,
        )
        evidence["provision"] = provision_result

        env_dir = project_dir / ".hyperspace" / "env"
        portable = portable_python(env_dir)
        env_dir_ok = native_python(env_dir).is_file() and (
            portable.with_name("python.exe").is_file() if IS_WINDOWS else portable.is_file()
        )
        db_ok = db_path.is_file()

        cfg = load_config(project_dir)
        config_ok = cfg.judge == "none"
        fallback_message = (provision_result.get("judge") or {}).get("message") or ""
        fallback_ok = bool(fallback_message)

        launcher_name = {
            "darwin": "Open Hyperspace.command",
            "win32": "Open Hyperspace.bat",
        }.get(sys.platform, "open-hyperspace.sh")
        launcher_path = project_dir / ".hyperspace" / launcher_name
        launcher_file_ok = launcher_path.is_file() and (
            sys.platform == "win32" or os.access(launcher_path, os.X_OK)
        )
        browser, record = _fake_browser(tmp_path / "fakebrowser")
        launcher_run = _run_launcher(launcher_path, port, env, browser, record)
        evidence["launcher_run"] = launcher_run
        console_page_ok = bool((launcher_run["console_page"] or {}).get("ok"))
        launcher_ok = launcher_file_ok and launcher_run["served"] and launcher_run["opened_ok"] and console_page_ok
        if IS_WINDOWS:
            without_env = _run_launcher_without_env(launcher_path, tmp_path, env)
            evidence["launcher_without_env"] = without_env
            launcher_ok = launcher_ok and without_env["refused_ok"]

        door = None
        api_ok = False
        api_body = None
        try:
            door = start(db_path, port=0)
            bound_port = door.server_address[1]
            with urllib.request.urlopen(f"http://127.0.0.1:{bound_port}/api/projects", timeout=5) as resp:
                api_ok = resp.status == 200
                api_body = json.loads(resp.read())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            evidence["door_error"] = _trim(str(exc))
        finally:
            if door is not None:
                door.shutdown()
                door.server_close()

        doctor_ok, doctor_lines = doctor(project_dir)

    after_freeze = _pip_freeze(sys.executable)
    site_packages_unchanged = before_freeze == after_freeze

    evidence.update({
        "env_dir_ok": env_dir_ok,
        "db_ok": db_ok,
        "config_judge": cfg.judge,
        "config_ok": config_ok,
        "fallback_message": fallback_message,
        "fallback_message_present": fallback_ok,
        "launcher_path": str(launcher_path),
        "launcher_ok": launcher_ok,
        "door_api_ok": api_ok,
        "door_api_body_type": type(api_body).__name__ if api_body is not None else None,
        "doctor_ok": doctor_ok,
        "doctor_lines": doctor_lines,
        "provisioning_tool": (provision_result.get("env") or {}).get("tool"),
        "site_packages_unchanged": site_packages_unchanged,
        "elapsed_seconds": round(time.time() - started_at, 2),
    })
    if not site_packages_unchanged:
        before_lines = set(before_freeze.splitlines())
        after_lines = set(after_freeze.splitlines())
        evidence["site_packages_diff"] = {
            "added": sorted(after_lines - before_lines),
            "removed": sorted(before_lines - after_lines),
        }

    passed = all([
        env_dir_ok, db_ok, config_ok, fallback_ok, launcher_ok,
        api_ok, doctor_ok, site_packages_unchanged,
    ])
    result = "PASS" if passed else "FAIL"
    write_verdict(args.out, probe="installer", result=result, evidence=evidence)

    print(
        f"installer: {result} (env={env_dir_ok} db={db_ok} config={config_ok} "
        f"fallback={fallback_ok} launcher={launcher_ok} door={api_ok} "
        f"doctor={doctor_ok} site_packages_unchanged={site_packages_unchanged})"
    )
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
