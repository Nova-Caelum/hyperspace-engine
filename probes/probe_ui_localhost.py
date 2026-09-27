#!/usr/bin/env python3
"""probes/probe_ui_localhost.py — T5: the shipped console bundle renders the
project and opens a work item through a REAL loopback door, with no Auth.js
session config anywhere in the serving process's environment.

Composes `probes/check_ui_build.py`'s `check_page` (never re-implemented) —
seeds the project/work-item names its own page check expects (its `SEED_*`
constants), starts the real door as a subprocess with `AUTH_SECRET`/
`POSTGRES_URL` stripped from its environment, and points `check_page` at it
via `--door` semantics.

Usage: imported by probes/run.py; PROBE = "ui_localhost"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402
import check_ui_build as cub  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROBE = "ui_localhost"

_AUTH_ENV_KEYS = ("AUTH_SECRET", "POSTGRES_URL")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect((host, port))
                return True
            except OSError:
                time.sleep(0.1)
    return False


def _seed(db_path: Path) -> None:
    from hyperspace.store import Store
    from hyperspace.tools import call_tool

    store = Store.init(db_path)
    try:
        result = call_tool(store, "upsert_project", {
            "code": cub.SEED_PROJECT["code"], "name": cub.SEED_PROJECT["name"],
        })
        if "error" in result:
            raise RuntimeError(f"seeding the project failed: {result['error']}")

        candidate = {
            "project": cub.SEED_PROJECT["code"], "external_id": cub.SEED_WORK_ITEM["external_id"],
            "name": cub.SEED_WORK_ITEM["name"], "type": "task", "state": "ready",
            "parent_work_item": None, "assignee_agent": None, "team": None,
            "idempotency_key": "ui-localhost-probe-create",
            "specification": {
                "problem": "The UI probe needs a real seeded work item for the page check to find.",
                "why_it_matters": "Without a real row the page has nothing to render or click into.",
                "context_pointer": "probes/probe_ui_localhost.py",
            },
            "source_references": [{"uri": "probes/probe_ui_localhost.py"}],
            "effort_level": "quick", "module": None,
            "acceptance_criteria": [
                {"statement": "The page check passes.", "verification": {"kind": "command_check", "check_id": "tests"}},
            ],
            "proposer_identity": "probe", "proposer_surface": "cli-mac", "uncertainty_notes": [],
        }
        result = call_tool(store, "upsert_work_item", candidate)
        if "error" in result:
            raise RuntimeError(f"seeding the work item failed: {result['error']}")
    finally:
        store.close()


def _auth_js_scan() -> list[str]:
    dist = ROOT / "ui" / "dist"
    hits: list[str] = []
    for path in sorted(dist.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for token in ("next-auth", "@auth/core", "@auth/"):
            if token in text:
                hits.append(f"{path.relative_to(ROOT)}: {token!r}")
    return hits


def run(out_dir, opts) -> bool:
    evidence: dict = {}
    dest = Path(out_dir) / f"{PROBE}.json"

    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        db_path = project_dir / ".hyperspace" / "graph.db"
        try:
            _seed(db_path)
        except RuntimeError as exc:
            write_verdict(dest, probe=PROBE, result="FAIL", evidence={"error": str(exc)})
            return False

        port = _free_port()
        venv_python = ROOT / ".venv" / "bin" / "python"
        hyperspace_bin = (venv_python.parent / "hyperspace") if venv_python.exists() else "hyperspace"

        env = {k: v for k, v in os.environ.items() if k not in _AUTH_ENV_KEYS}
        evidence["serve_env_keys"] = sorted(env.keys())
        evidence["auth_env_absent"] = not any(k in env for k in _AUTH_ENV_KEYS)

        serve_proc = subprocess.Popen(
            [str(hyperspace_bin), "serve", "--port", str(port), "--dir", str(project_dir)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        page_ok = False
        try:
            if not _wait_for_port("127.0.0.1", port, timeout=10.0):
                stdout, stderr = serve_proc.communicate(timeout=2)
                evidence["error"] = "server never came up"
                evidence["serve_stderr"] = stderr[-2000:]
                write_verdict(dest, probe=PROBE, result="FAIL", evidence=evidence)
                return False

            page_ok = cub.check_page(evidence, f"http://127.0.0.1:{port}/", getattr(opts, "source", None))
        finally:
            serve_proc.terminate()
            try:
                serve_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                serve_proc.kill()
                serve_proc.wait(timeout=5)

    auth_js_hits = _auth_js_scan()
    evidence["auth_js_scan"] = {"hits": auth_js_hits, "no_auth_js": not auth_js_hits}

    ok = bool(page_ok) and evidence["auth_env_absent"] and not auth_js_hits
    write_verdict(dest, probe=PROBE, result="PASS" if ok else "FAIL", evidence=evidence)
    return ok
