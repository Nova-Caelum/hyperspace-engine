#!/usr/bin/env python3
"""T4.2 verdict check: the loopback door serves the console's contract.

Two sub-checks, both must PASS:
  (a) `tests/test_http.py` passes under the repo's own venv.
  (b) a live smoke: `hyperspace init` in a temp dir, seed one project/module/
      work item/cycle/initiative/worklog entry through `call_tool`, launch
      `hyperspace serve --port <free>` as a real subprocess, hit every read
      route and every `POST /mcp` `tools/call` this row's acceptance text
      names, confirm `GET /` returns HTML, and confirm the bound address is
      `127.0.0.1` (a successful loopback connect, plus a best-effort
      `lsof`/`netstat` listener line recorded as evidence that it is not
      `0.0.0.0`) — then terminate the subprocess.

Usage: probes/check_http_contract.py --out <path>
"""
import argparse
import json
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
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _trim(text: str | None, limit: int = 4000) -> str:
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _venv_python() -> Path:
    venv_python = ROOT / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def _hyperspace_bin() -> Path:
    """The console-script entrypoint installed by `uv pip install -e .` —
    same venv the pytest sub-check runs under."""
    candidate = ROOT / ".venv" / "bin" / "hyperspace"
    if candidate.exists():
        return candidate
    found = shutil.which("hyperspace")
    if found:
        return Path(found)
    raise FileNotFoundError("no `hyperspace` console script found on .venv or PATH")


# ── (a) pytest ───────────────────────────────────────────────────────────

def check_pytest(evidence: dict) -> bool:
    python = _venv_python()
    proc = subprocess.run(
        [str(python), "-m", "pytest", "tests/test_http.py", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    summary_line = ""
    for line in proc.stdout.splitlines()[::-1]:
        if "passed" in line or "failed" in line or "error" in line:
            summary_line = line.strip()
            break
    evidence["pytest"] = {
        "command": f"{python} -m pytest tests/test_http.py -q",
        "exit_code": proc.returncode,
        "summary_line": summary_line,
        "stdout": _trim(proc.stdout),
        "stderr": _trim(proc.stderr),
    }
    return proc.returncode == 0


# ── (b) live smoke ───────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            try:
                sock.connect((host, port))
                return True
            except OSError:
                time.sleep(0.1)
    return False


def _http_get(base_url: str, path: str, headers: dict | None = None) -> tuple[int, str, bytes]:
    req = urllib.request.Request(base_url + path, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", exc.read()


def _http_post_mcp(base_url: str, name: str, arguments: dict) -> tuple[int, dict]:
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/mcp", data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _top_level_shape(body: bytes) -> str:
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "<non-json>"
    if isinstance(parsed, list):
        return f"list[{len(parsed)}]"
    if isinstance(parsed, dict):
        return f"dict(keys={sorted(parsed.keys())})"
    return str(type(parsed))


def _seed(db_path: Path) -> dict:
    sys.path.insert(0, str(ROOT))
    from hyperspace.store import Store
    from hyperspace.tools import call_tool

    store = Store.init(db_path)
    call_tool(store, "upsert_project", {"code": "http-check", "name": "HTTP Contract Check"})
    call_tool(store, "upsert_module", {
        "project": "http-check", "external_id": "http-check:mod-1", "name": "Check module",
        "acceptance_criteria": "Every work item under this module reaches done.",
    })
    wi = call_tool(store, "upsert_work_item", {
        "project": "http-check", "external_id": "http-check:wi-1", "name": "Check work item",
        "type": "task", "state": None, "parent_work_item": None, "assignee_agent": None,
        "team": None, "idempotency_key": "wi-1-create",
        "specification": {
            "problem": "The live smoke needs a real row to read back through every route.",
            "why_it_matters": "Without a seeded row the smoke cannot tell a 200 from an empty list.",
            "context_pointer": "probes/check_http_contract.py",
        },
        "source_references": [{"uri": "probes/check_http_contract.py"}],
        "effort_level": "quick", "module": None,
        "acceptance_criteria": [
            {"statement": "The route table check passes.", "verification": {"kind": "command_check", "check_id": "tests"}},
        ],
        "proposer_identity": "probe", "proposer_surface": "cli-mac", "uncertainty_notes": [],
    })
    call_tool(store, "upsert_cycle", {
        "project": "http-check", "external_id": "http-check:cy-1", "name": "Check cycle",
    })
    call_tool(store, "upsert_initiative", {"external_id": "http-check-init", "title": "Check initiative"})
    call_tool(store, "link_initiative_objects", {"initiative": "http-check-init", "projects": ["http-check"]})
    call_tool(store, "append_worklog", {
        "author": "probe", "project": "http-check", "summary": "Seeded the live-smoke store.",
    })
    store.close()
    return wi["row"]


def check_live_smoke(evidence: dict) -> bool:
    all_ok = True
    route_table: dict[str, str] = {}

    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        db_path = project_dir / ".hyperspace" / "graph.db"

        python = _venv_python()
        init_proc = subprocess.run(
            [str(_hyperspace_bin()), "init", "--dir", str(project_dir)],
            capture_output=True, text=True,
        )
        route_table["hyperspace init"] = f"exit={init_proc.returncode}"
        if init_proc.returncode != 0:
            evidence["live_smoke"] = {"error": "hyperspace init failed", "stderr": _trim(init_proc.stderr)}
            return False

        wi_row = _seed(db_path)

        port = _free_port()
        serve_proc = subprocess.Popen(
            [str(_hyperspace_bin()), "serve", "--port", str(port), "--dir", str(project_dir)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            if not _wait_for_port("127.0.0.1", port, timeout=10.0):
                stdout, stderr = serve_proc.communicate(timeout=2)
                evidence["live_smoke"] = {
                    "error": "server never came up",
                    "stdout": _trim(stdout), "stderr": _trim(stderr),
                }
                return False

            base_url = f"http://127.0.0.1:{port}"

            # every read route the acceptance text names, plus the brief's
            # ninth (initiative links).
            get_routes = [
                "/api/projects",
                "/api/projects/http-check/work-items",
                "/api/projects/http-check/modules",
                "/api/projects/http-check/cycles",
                f"/api/modules/http-check:mod-1",
                f"/api/work-items/{wi_row['external_id']}",
                "/api/initiatives",
                "/api/initiatives/http-check-init",
            ]
            for path in get_routes:
                status, _ctype, body = _http_get(base_url, path)
                route_table[f"GET {path}"] = f"{status} {_top_level_shape(body)}"
                if status != 200:
                    all_ok = False

            # initiative links — needs the initiative's row id from the item read above
            status, _ctype, init_body = _http_get(base_url, "/api/initiatives/http-check-init")
            init_row = json.loads(init_body) if status == 200 else {}
            init_id = init_row.get("id")
            if init_id:
                status, _ctype, body = _http_get(base_url, f"/api/initiatives/{init_id}/links")
                route_table[f"GET /api/initiatives/{init_id}/links"] = f"{status} {_top_level_shape(body)}"
                if status != 200:
                    all_ok = False
            else:
                all_ok = False
                route_table["GET /api/initiatives/<id>/links"] = "skipped: no initiative id"

            # unknown route -> 404 json
            status, ctype, body = _http_get(base_url, "/api/does-not-exist")
            route_table["GET /api/does-not-exist"] = f"{status} {ctype}"
            if status != 404 or "error" not in _top_level_shape(body):
                all_ok = False

            # POST /mcp — the four tools the acceptance text names
            mcp_calls = [
                ("get_recent_activity", {"limit": 5}),
                ("append_worklog", {"author": "probe", "project": "http-check", "summary": "via /mcp"}),
                ("list_agents", {}),
                ("upsert_work_item", {
                    "project": "http-check", "external_id": "http-check:wi-2", "name": "Second check item",
                    "type": "task", "state": None, "parent_work_item": None, "assignee_agent": None,
                    "team": None, "idempotency_key": "wi-2-create",
                    "specification": {
                        "problem": "The live smoke needs a second row filed through the JSON-RPC route.",
                        "why_it_matters": "Proves POST /mcp tools/call reaches the graph-tool table, not just GET.",
                        "context_pointer": "probes/check_http_contract.py",
                    },
                    "source_references": [{"uri": "probes/check_http_contract.py"}],
                    "effort_level": "quick", "module": None,
                    "acceptance_criteria": [
                        {"statement": "The route table check passes.", "verification": {"kind": "command_check", "check_id": "tests"}},
                    ],
                    "proposer_identity": "probe", "proposer_surface": "cli-mac", "uncertainty_notes": [],
                }),
            ]
            for name, arguments in mcp_calls:
                status, data = _http_post_mcp(base_url, name, arguments)
                is_error = isinstance(data.get("result"), dict) and data["result"].get("isError")
                route_table[f"POST /mcp {name}"] = f"{status} isError={bool(is_error)}"
                if status != 200 or "result" not in data or is_error:
                    all_ok = False

            # GET / -> the console page's index.html
            status, ctype, body = _http_get(base_url, "/")
            route_table["GET /"] = f"{status} {ctype}"
            is_html = ctype.startswith("text/html") and (b"<html" in body.lower() or b"<!doctype" in body.lower())
            if status != 200 or not is_html:
                all_ok = False

            # bound-address confirmation
            loopback_ok = _wait_for_port("127.0.0.1", port, timeout=1.0)
            listener_line = ""
            try:
                lsof = subprocess.run(
                    ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                    capture_output=True, text=True, timeout=5,
                )
                listener_line = _trim(lsof.stdout, 500)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                try:
                    netstat = subprocess.run(
                        ["netstat", "-an"], capture_output=True, text=True, timeout=5,
                    )
                    listener_line = "\n".join(
                        line for line in netstat.stdout.splitlines() if str(port) in line
                    )[:500]
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    listener_line = "<lsof/netstat unavailable>"

            bound_to_all_interfaces = "0.0.0.0" in listener_line or f"*.{port}" in listener_line
            evidence["bound_address"] = {
                "loopback_connect_ok": loopback_ok,
                "listener_line": listener_line,
                "bound_to_all_interfaces": bound_to_all_interfaces,
            }
            if not loopback_ok or bound_to_all_interfaces:
                all_ok = False
        finally:
            serve_proc.terminate()
            try:
                serve_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                serve_proc.kill()
                serve_proc.wait(timeout=5)

    evidence["route_table"] = route_table
    return all_ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    evidence: dict = {}
    a = check_pytest(evidence)
    b = check_live_smoke(evidence)

    result = "PASS" if (a and b) else "FAIL"
    write_verdict(args.out, probe="hsp_loopback_http_door", result=result, evidence=evidence)

    print(f"hsp_loopback_http_door: {result} (pytest={a} live_smoke={b})")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
