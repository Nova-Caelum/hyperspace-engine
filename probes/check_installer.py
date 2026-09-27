#!/usr/bin/env python3
"""T5.1 verdict check: a fresh-directory, non-interactive dry run of the
hyperspace-setup skill's steps — no key, no `claude`/`codex` on PATH.

Six sub-checks, all must PASS:
  (a) the real provisioning (`hyperspace.setup.provision.provision`) with the
      real `uv` on this Mac creates `.hyperspace/env`
  (b) `.hyperspace/graph.db` exists (`hyperspace init`'s store step)
  (c) `.hyperspace/config.toml` reads `judge = "none"` and the run captured
      the fallback message that names what was missing
  (d) the launcher for this platform exists and is executable (POSIX)
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
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hyperspace.config import load_config  # noqa: E402
from hyperspace.http.server import start  # noqa: E402
from hyperspace.setup.provision import doctor, provision  # noqa: E402
from hyperspace.store import Store  # noqa: E402

_HIDDEN_BINARIES = ("claude", "codex")
_SYSTEM_DIRS = ["/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin"]


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
        (shim_dir / "uv").symlink_to(real_uv)
        real_uvx = Path(real_uv).parent / "uvx"
        if real_uvx.exists():
            (shim_dir / "uvx").symlink_to(real_uvx)

    safe_system_dirs = [d for d in _SYSTEM_DIRS if Path(d).is_dir() and not _dir_has_any(d, _HIDDEN_BINARIES)]
    return os.pathsep.join([str(shim_dir), *safe_system_dirs])


def _fresh_env(shim_dir: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")}
    env["PATH"] = _build_stripped_path(shim_dir)
    return env


def _pip_freeze(python: str) -> str:
    proc = subprocess.run([python, "-m", "pip", "list", "--format=freeze"], capture_output=True, text=True)
    return proc.stdout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    evidence: dict = {}
    started_at = time.time()
    before_freeze = _pip_freeze(sys.executable)

    with tempfile.TemporaryDirectory() as tmp:
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

        project_dir = tmp_path / "fresh-project"
        project_dir.mkdir()
        db_path = project_dir / ".hyperspace" / "graph.db"
        Store.init(db_path).close()

        # `port=8791` mirrors the brief's own non-interactive example
        # (`hyperspace init --judge none --port 8791 --user user
        # --provision`) — the door's LIVE functional check just below binds
        # its own ephemeral `port=0` instead, so this config value is never
        # actually listened on during the probe.
        provision_result = provision(
            project_dir,
            judge=None, port=8791, user="user",
            prefer_uv=True, run=run_fn, which=which_fn, env=env,
            platform=sys.platform,
        )
        evidence["provision"] = provision_result

        env_dir_ok = (project_dir / ".hyperspace" / "env" / "bin" / "python").is_file()
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
        launcher_ok = launcher_path.is_file() and (
            sys.platform == "win32" or os.access(launcher_path, os.X_OK)
        )

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
