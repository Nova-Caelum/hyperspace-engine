#!/usr/bin/env python3
"""T4.3 verdict check: prebuilt console bundle — files, reproducibility, page.

Three sub-checks, all must PASS:
  (a) files: `ui/dist/index.html`, its assets, `ui/SOURCE.md`, `ui/build.sh`
      are present, and `ui/SOURCE.md` names the pinned commit (21a60c4).
  (b) reproducibility: `ui/build.sh` rebuilds the bundle from a fresh clone
      of the pinned commit — a local clone via `--source <path>` when given,
      else `ui/build.sh`'s own network default (`--source` omitted entirely,
      never a personal path); the rebuilt file list matches `ui/dist/`'s and
      every file's size is within 1% (differences beyond a hash mismatch
      from a build-time nonce are recorded, not silently accepted).
  (c) page: the bundle renders through a live door — either the real
      loopback door (`--door <url>`, when it exists) or a throwaway stdlib
      stub server that serves `ui/dist/` and answers the `/api/*` + `/mcp`
      calls the page makes with one seeded project and one seeded work
      item. `ui_page_check.mjs` drives a headless system-Chrome check
      against whichever URL is live and reports what it saw; playwright is
      resolved from `PLAYWRIGHT_MODULE` if set, else `<source>/node_modules/
      playwright/index.mjs` when `--source` names a local clone that already
      has it installed, else this sub-check fails honestly, naming both.

Usage: probes/check_ui_build.py --out <path> [--door <url>] [--source <path>]
"""
import argparse
import hashlib
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "ui" / "dist"
SOURCE_MD = ROOT / "ui" / "SOURCE.md"
BUILD_SH = ROOT / "ui" / "build.sh"
PINNED_COMMIT = "21a60c4"

SEED_PROJECT = {
    "code": "hsp-bundle-check",
    "name": "Hyperspace Bundle Check",
    "description": "Seed project for the hsp-ui-bundle reproducibility/page check.",
    "folder_path": "/projects/hsp-bundle-check",
    "created_at": "2026-09-01T00:00:00.000Z",
    "status": "in-progress",
    "team": ["engineer"],
    "owner": "maintainer",
    "client": "Nova Caelum",
}
SEED_WORK_ITEM = {
    "external_id": "hsp-bundle-check:bundle-check-task",
    "id": "11111111-1111-1111-1111-111111111111",
    "project_code": SEED_PROJECT["code"],
    "module_id": None,
    "parent_work_item_id": None,
    "name": "Bundle check task",
    "description": "Seed work item asserting the page renders through the loopback door.",
    "acceptance_criteria": None,
    "acceptance_criteria_ref": None,
    "state": "ready",
    "priority": "medium",
    "assignee_agent": "",
    "team": [],
    "blocked_by": [],
    "source_references": [],
    "position": None,
    "created_at": "2026-09-01T00:00:00.000Z",
}

UNHANDLED_API_GETS: list[str] = []


def _trim(text: str, limit: int = 4000) -> str:
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


# ── Part A: files ────────────────────────────────────────────────────────────

def check_files(evidence: dict) -> bool:
    index_html = DIST / "index.html"
    assets_dir = DIST / "assets"
    assets = list(assets_dir.glob("*")) if assets_dir.exists() else []
    source_text = SOURCE_MD.read_text() if SOURCE_MD.exists() else ""

    details = {
        "index_html_exists": index_html.exists(),
        "assets_present": bool(assets),
        "asset_count": len(assets),
        "source_md_exists": SOURCE_MD.exists(),
        "build_sh_exists": BUILD_SH.exists(),
        "build_sh_executable": bool(BUILD_SH.exists() and os.access(BUILD_SH, os.X_OK)),
        "source_names_pinned_commit": PINNED_COMMIT in source_text,
    }
    evidence["files"] = details
    return all(details[k] for k in (
        "index_html_exists", "assets_present", "source_md_exists",
        "build_sh_exists", "build_sh_executable", "source_names_pinned_commit",
    ))


# ── Part B: reproducibility ──────────────────────────────────────────────────

def _hash_tree(root: Path) -> dict:
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(root))
            files[rel] = (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
    return files


def check_reproducible(evidence: dict, source: str | None) -> bool:
    if not BUILD_SH.exists():
        evidence["reproducibility"] = {"error": "ui/build.sh missing"}
        return False

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "rebuild-dist"
        cmd = ["sh", str(BUILD_SH)]
        if source:
            cmd += ["--source", source]
        cmd += ["--commit", PINNED_COMMIT, "--out", str(out_dir)]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        build_evidence = {
            "command": " ".join(cmd),
            "exit_code": proc.returncode,
            "stdout": _trim(proc.stdout),
            "stderr": _trim(proc.stderr),
        }

        if proc.returncode != 0 or not out_dir.exists():
            evidence["reproducibility"] = {**build_evidence, "error": "rebuild failed or produced no output directory"}
            return False

        shipped = _hash_tree(DIST)
        rebuilt = _hash_tree(out_dir)
        shipped_files = set(shipped)
        rebuilt_files = set(rebuilt)
        file_list_matches = shipped_files == rebuilt_files

        hash_diffs = []
        size_within_tolerance = True
        for rel in sorted(shipped_files & rebuilt_files):
            s_size, s_hash = shipped[rel]
            r_size, r_hash = rebuilt[rel]
            if s_hash == r_hash:
                continue
            pct_diff = abs(s_size - r_size) / max(s_size, 1) * 100
            within_1pct = pct_diff <= 1.0
            hash_diffs.append({
                "file": rel,
                "shipped_size": s_size,
                "rebuilt_size": r_size,
                "pct_diff": round(pct_diff, 3),
                "within_1pct": within_1pct,
                "note": "hash differs — likely a build-time nonce; size compared instead",
            })
            if not within_1pct:
                size_within_tolerance = False

        evidence["reproducibility"] = {
            **build_evidence,
            "file_list_matches": file_list_matches,
            "shipped_only": sorted(shipped_files - rebuilt_files),
            "rebuilt_only": sorted(rebuilt_files - shipped_files),
            "hash_diffs": hash_diffs,
        }
        return bool(file_list_matches and size_within_tolerance)


# ── Part C: page (stub or real door) ────────────────────────────────────────

def _make_stub_handler():
    dist_dir = str(DIST)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=dist_dir, **kwargs)

        def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
            pass  # quiet; evidence is captured structurally, not from server logs

        def _send_json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - stdlib method name
            path = self.path.split("?", 1)[0]
            if path == "/api/projects":
                return self._send_json([SEED_PROJECT])
            if re.fullmatch(r"/api/projects/[^/]+/modules", path):
                return self._send_json([])
            if re.fullmatch(r"/api/projects/[^/]+/work-items", path):
                return self._send_json([SEED_WORK_ITEM])
            if re.fullmatch(r"/api/projects/[^/]+/cycles", path):
                return self._send_json([])
            if path == "/api/initiatives":
                return self._send_json([])
            if path.startswith("/api/"):
                UNHANDLED_API_GETS.append(path)
                return self._send_json([], status=404)
            return super().do_GET()

        def do_POST(self):  # noqa: N802 - stdlib method name
            if self.path == "/mcp":
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw or b"{}")
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                req_id = payload.get("id", 1)
                return self._send_json({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": "[]"}]},
                })
            self.send_response(404)
            self.end_headers()

    return Handler


def _start_stub_server():
    handler = _make_stub_handler()
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


def check_page(evidence: dict, door: str | None, source: str | None = None) -> bool:
    node = shutil.which("node")
    if node is None:
        evidence["page"] = {"error": "`node` not found on PATH"}
        return False

    env_module = os.environ.get("PLAYWRIGHT_MODULE")
    source_module = Path(source) / "node_modules" / "playwright" / "index.mjs" if source else None
    if env_module:
        playwright_module = Path(env_module)
    elif source_module is not None and source_module.exists():
        playwright_module = source_module
    else:
        evidence["page"] = {
            "error": (
                "no playwright module resolvable: PLAYWRIGHT_MODULE is unset, and "
                f"{'--source not given' if source is None else f'{source_module} does not exist'}"
            ),
        }
        return False
    if not playwright_module.exists():
        evidence["page"] = {"error": f"playwright module not found at {playwright_module}"}
        return False

    httpd = None
    if door:
        url = door
        mode = "door"
    else:
        httpd, port = _start_stub_server()
        url = f"http://127.0.0.1:{port}/"
        mode = "stub"

    try:
        try:
            proc = subprocess.run(
                [node, str(ROOT / "probes" / "ui_page_check.mjs"), url, SEED_PROJECT["name"], SEED_WORK_ITEM["name"]],
                capture_output=True,
                text=True,
                env={**os.environ, "PLAYWRIGHT_MODULE": str(playwright_module)},
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            evidence["page"] = {
                "mode": mode,
                "url": url,
                "error": "ui_page_check.mjs timed out after 120s",
                "stdout": _trim(exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")),
                "stderr": _trim(exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")),
                "unhandled_api_gets": sorted(set(UNHANDLED_API_GETS)),
            }
            return False
    finally:
        if httpd is not None:
            httpd.shutdown()

    page_json = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                page_json = json.loads(line)
            except json.JSONDecodeError:
                continue

    evidence["page"] = {
        "mode": mode,
        "url": url,
        "command_exit_code": proc.returncode,
        "stdout": _trim(proc.stdout),
        "stderr": _trim(proc.stderr),
        "result": page_json,
        "unhandled_api_gets": sorted(set(UNHANDLED_API_GETS)),
    }
    return bool(page_json and page_json.get("ok"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--door", default=None)
    parser.add_argument("--source", default=None,
                        help="local clone (or git URL) to rebuild from; omit to use "
                             "ui/build.sh's own network default")
    args = parser.parse_args(argv)

    evidence: dict = {}
    a = check_files(evidence)
    b = check_reproducible(evidence, args.source)
    c = check_page(evidence, args.door, args.source)

    result = "PASS" if (a and b and c) else "FAIL"
    write_verdict(args.out, probe="ui_build", result=result, evidence=evidence)

    print(f"ui_build: {result} (files={a} reproducible={b} page={c})")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
