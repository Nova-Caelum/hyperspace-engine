#!/usr/bin/env python3
"""T4.1 verdict check: the stdio MCP server Claude Code spawns per session.

Two sub-checks, both must PASS:
  (a) `tests/test_mcp_stdio.py` passes under the repo's own venv.
  (b) a live scripted stdio session: `tools/list` (record the names), one
      `tools/call` per the seven required tools against a fresh temp project
      (record `isError` and the top-level result keys), then confirms the
      loopback door answered on its configured port after the first call.

Usage: probes/check_mcp_stdio.py --out <path>
"""
import argparse
import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "mcp-stdio-probe"

REQUIRED_TOOL_NAMES = [
    "complete_workitem", "upsert_work_item", "get_graph_run", "list_work_items",
    "append_worklog", "link_work_items", "upsert_module",
]


def _trim(text: str | None, limit: int = 4000) -> str:
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _venv_python() -> Path:
    venv_python = ROOT / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


# ── (a) pytest ───────────────────────────────────────────────────────────


def check_pytest(evidence: dict) -> bool:
    python = _venv_python()
    proc = subprocess.run(
        [str(python), "-m", "pytest", "tests/test_mcp_stdio.py", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    summary_line = ""
    for line in proc.stdout.splitlines()[::-1]:
        if "passed" in line or "failed" in line or "error" in line:
            summary_line = line.strip()
            break
    evidence["pytest"] = {
        "command": f"{python} -m pytest tests/test_mcp_stdio.py -q",
        "exit_code": proc.returncode,
        "summary_line": summary_line,
        "stdout": _trim(proc.stdout),
        "stderr": _trim(proc.stderr),
    }
    return proc.returncode == 0


# ── (b) live scripted stdio session ─────────────────────────────────────


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _init_project(project_dir: Path, port: int) -> None:
    sys.path.insert(0, str(ROOT))
    from hyperspace.store import Store

    db_path = project_dir / ".hyperspace" / "graph.db"
    store = Store.init(db_path)
    store.close()
    (project_dir / ".hyperspace" / "config.toml").write_text(f"port = {port}\n")


def _candidate(ext: str, criteria: list[dict]) -> dict:
    return {
        "project": PROJECT, "external_id": ext, "name": "MCP stdio probe item",
        "type": "task", "state": "ready", "parent_work_item": None,
        "assignee_agent": None, "team": None, "idempotency_key": f"{ext}-create",
        "specification": {
            "problem": "The stdio server row needs a real filed work item to exercise "
                       "complete_workitem end to end over the wire.",
            "why_it_matters": "Without a real filing, this probe cannot prove the seven "
                               "required tools dispatch through the live server.",
            "context_pointer": "probes/check_mcp_stdio.py",
        },
        "source_references": [{"uri": "probes/check_mcp_stdio.py"}],
        "effort_level": "quick", "module": None,
        "acceptance_criteria": criteria,
        "proposer_identity": "probe", "proposer_surface": "cli-mac",
        "uncertainty_notes": [],
    }


def _content_json(result) -> dict:
    return json.loads(result.content[0].text)


def _http_get(base_url: str, path: str) -> int:
    req = urllib.request.Request(base_url + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


async def _live_scenario(project_dir: Path, port: int, evidence: dict) -> bool:
    from mcp import StdioServerParameters
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client
    import os

    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    params = StdioServerParameters(command=str(_venv_python()), args=["-m", "hyperspace.mcp"], env=env)

    all_ok = True
    tool_results: dict = {}

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            names = sorted(t.name for t in listed.tools)
            evidence["tools_list"] = names
            missing = [n for n in REQUIRED_TOOL_NAMES if n not in names]
            if missing:
                all_ok = False
                evidence["missing_required_tools"] = missing

            setup = await session.call_tool("upsert_project", {"code": PROJECT, "name": "MCP stdio probe"})
            if setup.is_error:
                all_ok = False

            file_criterion = {
                "statement": "The result file is created by the work.",
                "verification": {"kind": "file_state", "path": "out/result.txt", "assertion": "exists"},
            }
            ext1 = f"{PROJECT}:wi-1"
            filed = await session.call_tool("upsert_work_item", _candidate(ext1, [file_criterion]))
            tool_results["upsert_work_item"] = {"isError": filed.is_error, "keys": None}
            if filed.is_error:
                all_ok = False
            else:
                payload = _content_json(filed)
                tool_results["upsert_work_item"]["keys"] = sorted(payload.keys())
                filing_id = payload["filing_id"]

                ext2 = f"{PROJECT}:wi-2"
                trivial_criterion = {
                    "statement": "The second probe item exists for linking.",
                    "verification": {"kind": "command_check", "check_id": "tests"},
                }
                filed2 = await session.call_tool("upsert_work_item", _candidate(ext2, [trivial_criterion]))
                if filed2.is_error:
                    all_ok = False

                run = await session.call_tool("get_graph_run", {"run_id": filing_id})
                tool_results["get_graph_run"] = {"isError": run.is_error, "keys": None}
                if run.is_error:
                    all_ok = False
                else:
                    tool_results["get_graph_run"]["keys"] = sorted(_content_json(run).keys())

                listed_items = await session.call_tool("list_work_items", {"project": PROJECT})
                tool_results["list_work_items"] = {"isError": listed_items.is_error, "keys": None}
                if listed_items.is_error:
                    all_ok = False
                else:
                    tool_results["list_work_items"]["keys"] = "list"

                logged = await session.call_tool(
                    "append_worklog",
                    {"author": "probe", "project": PROJECT, "summary": "MCP stdio server probe."},
                )
                tool_results["append_worklog"] = {"isError": logged.is_error, "keys": None}
                if logged.is_error:
                    all_ok = False
                else:
                    tool_results["append_worklog"]["keys"] = sorted(_content_json(logged).keys())

                linked = await session.call_tool("link_work_items", {
                    "project": PROJECT, "item": ext1, "related_item": ext2, "relation_type": "relates-to",
                })
                tool_results["link_work_items"] = {"isError": linked.is_error, "keys": None}
                if linked.is_error:
                    all_ok = False
                else:
                    tool_results["link_work_items"]["keys"] = sorted(_content_json(linked).keys())

                mod = await session.call_tool("upsert_module", {
                    "project": PROJECT, "external_id": f"{PROJECT}:mod-1", "name": "Probe module",
                    "acceptance_criteria": "Every child work item in this module reaches the done state.",
                })
                tool_results["upsert_module"] = {"isError": mod.is_error, "keys": None}
                if mod.is_error:
                    all_ok = False
                else:
                    tool_results["upsert_module"]["keys"] = sorted(_content_json(mod).keys())

                (project_dir / "out").mkdir(parents=True, exist_ok=True)
                (project_dir / "out" / "result.txt").write_text("result\n")

                closed = await session.call_tool("complete_workitem", {
                    "project": PROJECT, "external_id": ext1,
                    "touched": [{"path": "out/result.txt", "effect": "created"}],
                    "idempotency_key": f"{ext1}-done",
                    "proposer_identity": "probe", "proposer_surface": "cli-mac",
                })
                tool_results["complete_workitem"] = {"isError": closed.is_error, "keys": None}
                if closed.is_error:
                    all_ok = False
                else:
                    closed_payload = _content_json(closed)
                    tool_results["complete_workitem"]["keys"] = sorted(closed_payload.keys())
                    if closed_payload.get("outcome") != "done":
                        all_ok = False

            # door check — after the first tools/call above
            status = _http_get(f"http://127.0.0.1:{port}", "/api/projects")
            evidence["door_status"] = status
            if status != 200:
                all_ok = False

    evidence["tool_results"] = tool_results
    return all_ok


def check_live_smoke(evidence: dict) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        port = _free_port()
        _init_project(project_dir, port)
        try:
            return asyncio.run(_live_scenario(project_dir, port, evidence))
        except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
            evidence["live_smoke_error"] = f"{type(exc).__name__}: {exc}"
            return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    evidence: dict = {}
    a = check_pytest(evidence)
    b = check_live_smoke(evidence)

    result = "PASS" if (a and b) else "FAIL"
    write_verdict(args.out, probe="hsp_local_mcp_server", result=result, evidence=evidence)

    print(f"hsp_local_mcp_server: {result} (pytest={a} live_smoke={b})")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
