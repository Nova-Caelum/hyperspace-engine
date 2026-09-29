"""tests/test_mcp_stdio.py — T4.1: the stdio MCP server Claude Code spawns per
session.

Spawns `.venv/bin/python -m hyperspace.mcp` as a real subprocess and speaks
JSON-RPC over its stdin/stdout with the `mcp` SDK's own client
(`stdio_client` + `ClientSession`, confirmed via context7 — see
`hyperspace/mcp/server.py`'s module docstring for the calls relied on).

Covers: `initialize` -> `tools/list` names every required tool with a
non-empty `inputSchema`; a scripted `tools/call` of each of the seven
required tools against a temporary store returns a result, not a protocol
error; a `ToolError` (missing/invalid criteria) comes back as
`isError: true` with the message, never a raised JSON-RPC error; the
loopback door lazily starts on the first `tools/call` and answers
`GET /api/projects`; a second server process against the same project
adopts the already-bound door rather than failing to bind; a project with
no `.hyperspace/graph.db` still answers `tools/list` (schema needs no
store) but every `tools/call` refuses naming `hyperspace init`; and the
server module carries no `from __future__ import annotations` (the
canonical stdio server's probed constraint — see the module's docstring).
"""
import asyncio
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

from hyperspace.store import Store

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT = "mcp-stdio-check"

REQUIRED_TOOL_NAMES = [
    "complete_workitem", "upsert_work_item", "get_graph_run", "list_work_items",
    "append_worklog", "link_work_items", "upsert_module",
]


# ── fixtures / helpers ───────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _venv_python() -> Path:
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def _server_params(project_dir: Path) -> StdioServerParameters:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    return StdioServerParameters(command=str(_venv_python()), args=["-m", "hyperspace.mcp"], env=env)


def _init_project(tmp_path: Path, name: str, port: int) -> Path:
    """A temp project dir with `.hyperspace/graph.db` (via `Store.init`) and a
    `config.toml` naming a free port — no git checkout needed (the landing
    check falls back to file mtimes)."""
    project_dir = tmp_path / name
    project_dir.mkdir()
    db_path = project_dir / ".hyperspace" / "graph.db"
    store = Store.init(db_path)
    store.close()
    (project_dir / ".hyperspace" / "config.toml").write_text(f"port = {port}\n", encoding="utf-8")
    return project_dir


def _candidate(ext: str, criteria: list[dict], **overrides) -> dict:
    payload = {
        "project": PROJECT, "external_id": ext, "name": "MCP stdio check item",
        "type": "task", "state": "ready", "parent_work_item": None,
        "assignee_agent": None, "team": None, "idempotency_key": f"{ext}-create",
        "specification": {
            "problem": "The stdio server row needs a real filed work item to exercise "
                       "complete_workitem end to end over the wire.",
            "why_it_matters": "Without a real filing, the RED/GREEN test cannot prove the "
                               "seven required tools dispatch through this server.",
            "context_pointer": "tests/test_mcp_stdio.py",
        },
        "source_references": [{"uri": "tests/test_mcp_stdio.py"}],
        "effort_level": "quick", "module": None,
        "acceptance_criteria": criteria,
        "proposer_identity": "engineer", "proposer_surface": "cli-mac",
        "uncertainty_notes": [],
    }
    payload.update(overrides)
    return payload


def _content_json(result) -> dict:
    assert result.content and result.content[0].type == "text", result
    return json.loads(result.content[0].text)


async def _session(project_dir: Path):
    """Async context manager: spawns the server and yields an initialized
    `ClientSession`."""
    return stdio_client(_server_params(project_dir))


def _http_get(base_url: str, path: str) -> tuple[int, bytes]:
    req = urllib.request.Request(base_url + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


# ── (1) full happy-path: list, call the seven, door lazy-start, adoption ────


def test_stdio_server_lists_and_calls_all_tools_and_starts_door(tmp_path):
    port = _free_port()
    project_dir = _init_project(tmp_path, "proj", port)

    async def scenario():
        async with stdio_client(_server_params(project_dir)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # ── tools/list ───────────────────────────────────────────
                listed = await session.list_tools()
                names = {t.name for t in listed.tools}
                for required in REQUIRED_TOOL_NAMES:
                    assert required in names, f"missing required tool: {required}"
                for tool in listed.tools:
                    assert tool.input_schema, f"{tool.name} has an empty inputSchema"

                # ── setup: a project row (FK requirement for work items) ──
                setup = await session.call_tool("upsert_project", {"code": PROJECT, "name": "MCP stdio check"})
                assert not setup.is_error, setup

                # ── upsert_work_item (the file_state row for complete_workitem) ──
                file_criterion = {
                    "statement": "The result file is created by the work.",
                    "verification": {"kind": "file_state", "path": "out/result.txt", "assertion": "exists"},
                }
                ext1 = f"{PROJECT}:wi-1"
                filed = await session.call_tool("upsert_work_item", _candidate(ext1, [file_criterion]))
                assert not filed.is_error, filed
                filed_payload = _content_json(filed)
                filing_id = filed_payload["filing_id"]

                # A second, unrelated work item so link_work_items has something real to link.
                ext2 = f"{PROJECT}:wi-2"
                trivial_criterion = {
                    "statement": "The second check item exists for linking.",
                    "verification": {"kind": "command_check", "check_id": "tests"},
                }
                filed2 = await session.call_tool("upsert_work_item", _candidate(ext2, [trivial_criterion]))
                assert not filed2.is_error, filed2

                # ── get_graph_run ──────────────────────────────────────────
                run = await session.call_tool("get_graph_run", {"run_id": filing_id})
                assert not run.is_error, run
                run_payload = _content_json(run)
                assert run_payload["external_id"] == ext1

                # ── list_work_items ────────────────────────────────────────
                listed_items = await session.call_tool("list_work_items", {"project": PROJECT})
                assert not listed_items.is_error, listed_items

                # ── append_worklog ──────────────────────────────────────────
                logged = await session.call_tool(
                    "append_worklog",
                    {"author": "engineer", "project": PROJECT, "summary": "MCP stdio server check."},
                )
                assert not logged.is_error, logged

                # ── link_work_items ──────────────────────────────────────────
                linked = await session.call_tool("link_work_items", {
                    "project": PROJECT, "item": ext1, "related_item": ext2, "relation_type": "relates-to",
                })
                assert not linked.is_error, linked

                # ── upsert_module ──────────────────────────────────────────
                mod = await session.call_tool("upsert_module", {
                    "project": PROJECT, "external_id": f"{PROJECT}:mod-1", "name": "Check module",
                    "acceptance_criteria": "Every child work item in this module reaches the done state.",
                })
                assert not mod.is_error, mod

                # ── a ToolError comes back as isError, not a protocol error ──
                bad = await session.call_tool("upsert_work_item", {
                    "project": PROJECT, "external_id": f"{PROJECT}:bad", "name": "Missing criteria",
                    "type": "task", "state": "ready", "parent_work_item": None, "assignee_agent": None,
                    "team": None, "idempotency_key": "bad-create",
                    "specification": {
                        "problem": "x" * 41, "why_it_matters": "y" * 41, "context_pointer": "z" * 21,
                    },
                    "source_references": [{"uri": "tests/test_mcp_stdio.py"}],
                    "effort_level": "quick", "module": None,
                    "acceptance_criteria": [],  # invalid: min_length=1
                    "proposer_identity": "engineer", "proposer_surface": "cli-mac",
                    "uncertainty_notes": [],
                })
                assert bad.is_error, "a ToolError-shaped refusal must set isError, not raise"
                assert bad.content and "acceptance_criteria" in bad.content[0].text.lower() or \
                    "criteria" in bad.content[0].text.lower()

                # ── create the result file, THEN close via complete_workitem ──
                (project_dir / "out").mkdir(parents=True, exist_ok=True)
                (project_dir / "out" / "result.txt").write_text("result\n", encoding="utf-8")

                closed = await session.call_tool("complete_workitem", {
                    "project": PROJECT, "external_id": ext1,
                    "touched": [{"path": "out/result.txt", "effect": "created"}],
                    "idempotency_key": f"{ext1}-done",
                    "proposer_identity": "engineer", "proposer_surface": "cli-mac",
                })
                assert not closed.is_error, closed
                closed_payload = _content_json(closed)
                assert closed_payload["outcome"] == "done", closed_payload

                # ── the loopback door started lazily after the first call ──
                status, _body = _http_get(f"http://127.0.0.1:{port}", "/api/projects")
                assert status == 200

                # ── a second server process against the same project adopts,
                #    it does not fail to (re)bind ────────────────────────────
                async with stdio_client(_server_params(project_dir)) as (read2, write2):
                    async with ClientSession(read2, write2) as session2:
                        await session2.initialize()
                        again = await session2.call_tool("list_work_items", {"project": PROJECT})
                        assert not again.is_error, again

                status2, _body2 = _http_get(f"http://127.0.0.1:{port}", "/api/projects")
                assert status2 == 200

    asyncio.run(scenario())


# ── (2) missing store: tools/list still answers, tools/call refuses ────────


def test_missing_store_lists_but_refuses_calls(tmp_path):
    project_dir = tmp_path / "no-store"
    project_dir.mkdir()

    async def scenario():
        async with stdio_client(_server_params(project_dir)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {t.name for t in listed.tools}
                for required in REQUIRED_TOOL_NAMES:
                    assert required in names

                result = await session.call_tool("list_work_items", {"project": PROJECT})
                assert result.is_error
                text = result.content[0].text.lower()
                assert "hyperspace init" in text

    asyncio.run(scenario())


# ── (3) the module carries no `from __future__ import annotations` ────────


def test_server_module_has_no_future_annotations_import():
    source = (REPO_ROOT / "hyperspace" / "mcp" / "server.py").read_text(encoding="utf-8")
    assert "from __future__ import annotations" not in source


# ── judge selection (controller D10 swap after the judge row landed) ──────────


def test_mcp_uses_the_configured_judge(tmp_path):
    from hyperspace.mcp.server import _judge_for

    project = tmp_path / "proj"
    Store.init(project / ".hyperspace" / "graph.db")
    assert _judge_for(project).name == "none"  # nothing configured → none
    (project / ".hyperspace" / "config.toml").write_text('judge = "claude-code"\n', encoding="utf-8")
    assert _judge_for(project).name == "claude-code"
