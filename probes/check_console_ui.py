#!/usr/bin/env python3
"""probes/check_console_ui.py — the console's round-1 browser checks (row HSE-94),
run through the real loopback door in a fresh, provisioned project.

Three checks, all must PASS (see `probes/ui_console_checks.mjs` for each step):
  create   a task with acceptance criteria shorter than 20 characters is refused
           and the server's reason is on screen; a valid task and a module are
           then created from the page and read back from the door.
  worklog  the Worklog tab's column order, value filter, hidden column, frozen
           column and sort all survive a reload; the hidden column comes back.
  runs     the project and module pages show the empty-state sentence with no
           runs, then the open run's goal and step name (never the closed run's).

What it does:
  1. `hyperspace init --dir <tmp> --provision --judge none` with this checkout's
     CLI, so the fresh project's `.hyperspace/env` carries this checkout's code
     and this checkout's `ui/dist`.
  2. `--dist <dir>` (a bundle from `ui/build.sh --out <dir>`): replace the
     provisioned env's `ui/dist` with it, so a candidate bundle is checked through
     the real door without touching this checkout's `ui/dist`. Omitted: the
     checkout's own bundle is checked.
  3. Start the env's own `hyperspace serve`, seed through the door's own routes
     (one project, one module, four worklog entries), then drive
     `probes/ui_console_checks.mjs` with headless system Chrome.

Playwright resolves like `check_ui_build.py`: `PLAYWRIGHT_MODULE` if set, else
`<source>/node_modules/playwright/index.mjs` for `--source <caelos clone>`.

Usage: probes/check_console_ui.py --out <verdict.json> [--dist <dir>]
       [--source <caelos clone>] [--shots <dir>] [--keep]
Exit 0 on PASS, 1 on FAIL.
"""
from __future__ import annotations

import argparse
import hashlib
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from hyperspace.venv_paths import find_venv_python  # noqa: E402

PROBE = "console_ui"
PAGE_SCRIPT = ROOT / "probes" / "ui_console_checks.mjs"
_AUTH_ENV_KEYS = ("AUTH_SECRET", "POSTGRES_URL")

PROJECT = {"code": "console-check", "name": "Console Check"}
MODULE = {"external_id": "runs-check-module", "name": "Runs check module"}
WORKLOG = [
    {"author": "designer", "summary": "Sketched the worklog tab", "tags": ["console", "design"],
     "surface": "cli-mac", "detailed": "Column order, filters, hidden and frozen columns, sort."},
    {"author": "engineer", "summary": "Served the worklog read", "tags": ["door"],
     "surface": "cli-pc", "client": "acme", "detailed": "GET /api/worklog?project=<code>."},
    {"author": "designer", "summary": "Wired the open runs section", "tags": ["console", "runs"],
     "surface": "desktop-mac", "detailed": "Project and module pages."},
    {"author": "cto", "summary": "Reviewed the round", "tags": ["review"],
     "surface": "cli-mac", "detailed": "Three browser checks."},
]


def _trim(text: str | None, limit: int = 4000) -> str:
    text = text or ""
    return text if len(text) <= limit else text[-limit:]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_door(port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/projects", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    return False


def _request(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def _mcp(base: str, name: str, arguments: dict) -> dict:
    status, payload = _request(base, "POST", "/mcp", {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments},
    })
    result = (payload or {}).get("result") or {}
    if status != 200 or result.get("isError") or "error" in (payload or {}):
        raise RuntimeError(f"{name}: {status} {json.dumps(payload)[:300]}")
    return json.loads(result["content"][0]["text"])


def seed(base: str) -> dict:
    """Seed through the door's own routes — the same ones the console uses."""
    _mcp(base, "upsert_project", {"code": PROJECT["code"], "name": PROJECT["name"]})
    status, row = _request(base, "POST", f"/api/projects/{PROJECT['code']}/modules", {
        "external_id": MODULE["external_id"], "name": MODULE["name"], "description": None,
        "acceptance_criteria": None, "acceptance_criteria_ref": None, "state": "ready",
        "team": [], "folder_path": None, "idempotency_key": "console-check-module",
    })
    if status != 200:
        raise RuntimeError(f"module create: {status} {row}")
    entries = [_mcp(base, "append_worklog", {"project": PROJECT["code"], **entry}) for entry in WORKLOG]
    return {"project": PROJECT["code"], "module": MODULE["external_id"], "worklog_entries": len(entries)}


def _playwright_module(source: str | None) -> Path | None:
    env_module = os.environ.get("PLAYWRIGHT_MODULE")
    if env_module:
        return Path(env_module)
    if source:
        candidate = Path(source) / "node_modules" / "playwright" / "index.mjs"
        if candidate.exists():
            return candidate
    return None


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_checks(evidence: dict, *, dist: str | None, source: str | None, shots: str | None,
               keep: bool) -> bool:
    node = shutil.which("node")
    playwright = _playwright_module(source)
    if node is None or playwright is None or not playwright.exists():
        evidence["error"] = (
            "need `node` on PATH and a playwright module (PLAYWRIGHT_MODULE, or --source <caelos clone> "
            "with node_modules/playwright)"
        )
        return False
    if dist and not (Path(dist) / "index.html").is_file():
        evidence["error"] = f"--dist {dist} has no index.html"
        return False

    venv_python = find_venv_python(ROOT / ".venv") or Path(sys.executable)
    cli = shutil.which("hyperspace", path=str(venv_python.parent)) or "hyperspace"
    project_dir = Path(tempfile.mkdtemp(prefix="hse-console-check-"))
    evidence["project_dir"] = str(project_dir) if keep else "(temporary, removed)"
    door = None
    try:
        init = subprocess.run(
            [cli, "init", "--dir", str(project_dir), "--provision", "--judge", "none"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=900,
        )
        evidence["init"] = {"exit_code": init.returncode, "stdout": _trim(init.stdout, 1500),
                            "stderr": _trim(init.stderr, 1500)}
        env_python = find_venv_python(project_dir / ".hyperspace" / "env")
        if init.returncode != 0 or env_python is None:
            evidence["error"] = "hyperspace init --provision failed"
            return False

        # `-I` and the project as cwd: the env's own installed package, never a
        # `hyperspace/` that happens to sit in the current directory (this checkout).
        where = subprocess.run(
            [str(env_python), "-I", "-c", "import hyperspace.http.server as s; print(s._DIST_DIR)"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=60, cwd=project_dir,
        )
        served_dist = Path(where.stdout.strip()).resolve()
        if not served_dist.is_relative_to(project_dir.resolve()):
            evidence["error"] = f"the provisioned env serves {served_dist}, outside the fresh project — refusing to touch it"
            return False
        if dist:
            shutil.rmtree(served_dist, ignore_errors=True)
            shutil.copytree(dist, served_dist)
        expected_index = served_dist / "index.html"
        evidence["bundle"] = {
            "source": dist or "this checkout's ui/dist (installed by --provision)",
            "served_from": "the provisioned env's ui/dist",
            "index_html_sha256": _hash(expected_index) if expected_index.is_file() else None,
            "assets": sorted(p.name for p in (served_dist / "assets").glob("*")) if (served_dist / "assets").is_dir() else [],
        }

        port = _free_port()
        env_cli = shutil.which("hyperspace", path=str(env_python.parent)) or str(env_python.parent / "hyperspace")
        env = {k: v for k, v in os.environ.items() if k not in _AUTH_ENV_KEYS}
        door = subprocess.Popen(
            [env_cli, "serve", "--port", str(port), "--dir", str(project_dir)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", env=env,
        )
        if not _wait_for_door(port):
            evidence["error"] = "the door never answered GET /api/projects"
            return False
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            served_index = hashlib.sha256(resp.read()).hexdigest()
        evidence["door"] = {"url": base + "/", "command": "<project>/.hyperspace/env hyperspace serve",
                            "served_index_html_sha256": served_index}
        if served_index != evidence["bundle"]["index_html_sha256"]:
            evidence["error"] = "the door is not serving the bundle under check"
            return False
        evidence["seed"] = seed(base)

        config = {
            "url": base + "/", "project_dir": str(project_dir), "project_code": PROJECT["code"],
            "project_name": PROJECT["name"], "module_name": MODULE["name"],
        }
        if shots:
            config["shots_dir"] = str(Path(shots).resolve())
        try:
            page = subprocess.run(
                [node, str(PAGE_SCRIPT), json.dumps(config)],
                capture_output=True, encoding="utf-8", errors="replace", timeout=300,
                env={**os.environ, "PLAYWRIGHT_MODULE": str(playwright)},
            )
        except subprocess.TimeoutExpired:
            evidence["error"] = "ui_console_checks.mjs timed out after 300s"
            return False
        result = None
        for line in page.stdout.splitlines():
            if line.strip().startswith("{"):
                try:
                    result = json.loads(line)
                except json.JSONDecodeError:
                    continue
        evidence["page"] = {"exit_code": page.returncode, "result": result, "stderr": _trim(page.stderr, 2000)}
        return bool(result and result.get("ok"))
    finally:
        if door is not None:
            stop_tree(door)
        if not keep:
            shutil.rmtree(project_dir, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="probes/check_console_ui.py")
    parser.add_argument("--out", required=True, help="verdict JSON path")
    parser.add_argument("--dist", default=None, help="bundle directory to serve instead of this checkout's ui/dist")
    parser.add_argument("--source", default=None, help="Caelos clone whose node_modules has playwright")
    parser.add_argument("--shots", default=None, help="directory for element-cropped screenshots")
    parser.add_argument("--keep", action="store_true", help="keep the temporary project directory")
    args = parser.parse_args(argv)

    evidence: dict = {}
    ok = run_checks(evidence, dist=args.dist, source=args.source, shots=args.shots, keep=args.keep)
    result = "PASS" if ok else "FAIL"
    write_verdict(args.out, probe=PROBE, result=result, evidence=evidence)
    checks = ((evidence.get("page") or {}).get("result") or {}).get("checks") or {}
    summary = " ".join(f"{name}={'PASS' if c.get('ok') else 'FAIL'}" for name, c in checks.items())
    print(f"{PROBE}: {result} ({summary or evidence.get('error', 'no page result')})")
    for name, check in checks.items():
        for error in check.get("errors", []):
            print(f"  {name}: {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
