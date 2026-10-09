"""tests/test_http_console.py — the console's writes and the two reads the task
console reads (row HSE-94, part A: the engine's web door).

The request bodies below are the ones `Caelos/src/app/App.tsx` builds in
`api()` (pinned `dfcb46d`, identical at `main` `85fe81c`): the `backendBody`
literals for work-items, modules and cycles, `POST /api/initiatives`, the
batched-link splitter, and the archive PATCH. Each is sent to a door over a
fresh store whose only row is a project, the way a new user's first project is
made (`POST /mcp upsert_project`, which the door has always served).
"""
from __future__ import annotations

import json
import sys
from http.client import HTTPConnection
from pathlib import Path

import pytest

from hyperspace.http.server import Door, start
from hyperspace.store import Store
from hyperspace.tools import call_tool

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

PROJECT = "my-first-project-0001"


# ── the console's bodies, as App.tsx builds them ─────────────────────────────


def task_body(**over) -> dict:
    """`api()`'s work-items POST builder: every key present, absent values null."""
    body = {
        "external_id": "wi-1760000000000-abc123",
        "name": "Write the onboarding email",
        "type": "task",
        "state": "ready",
        "description": "Draft the welcome email new users get after install.",
        "acceptance_criteria": "The draft email is saved to docs/welcome.md and reads cleanly.",
        "acceptance_criteria_ref": None,
        "assignee_agent": None,
        "team": [],
        "idempotency_key": "idem-1760000000000-def456",
    }
    body.update(over)
    return body


def module_body(**over) -> dict:
    body = {
        "external_id": "mod-1760000000001-ghi789",
        "name": "Onboarding",
        "description": "Everything about first-run onboarding.",
        "acceptance_criteria": "Every onboarding task is done and the welcome flow works end to end.",
        "acceptance_criteria_ref": None,
        "state": "pending-review",
        "team": [],
        "folder_path": None,
        "idempotency_key": "idem-1760000000001-jkl012",
    }
    body.update(over)
    return body


def cycle_body(**over) -> dict:
    body = {
        "external_id": "cy-1760000000002-mno345",
        "name": "Week 1",
        "description": None,
        "state": "planned",
        "start_date": None,
        "end_date": None,
        "idempotency_key": "idem-1760000000002-pqr678",
    }
    body.update(over)
    return body


def initiative_body(**over) -> dict:
    body = {
        "external_id": "init-1760000000003-stu901",
        "title": "Launch",
        "description": None,
        "state": "planned",
        "idempotency_key": "idem-1760000000003-vwx234",
    }
    body.update(over)
    return body


# ── harness ──────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_db(tmp_path):
    """A fresh engine project: a store with one project, made through the same
    tool the console calls (`upsert_project` over `/mcp`)."""
    db_path = tmp_path / ".hyperspace" / "graph.db"
    store = Store.init(db_path)
    call_tool(store, "upsert_project", {"code": PROJECT, "name": "My first project"})
    store.close()
    return db_path


@pytest.fixture
def door(fresh_db):
    door = start(fresh_db, port=0)
    try:
        yield door
    finally:
        door.shutdown()
        door.server_close()


def request(door: Door, method: str, path: str, body=None, raw: bytes | None = None):
    """`(status, parsed JSON body)`; `raw` sends bytes verbatim (a bad body)."""
    conn = HTTPConnection(door.server_address[0], door.server_address[1])
    try:
        payload = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
        conn.request(method, path, body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, json.loads(data)
    finally:
        conn.close()


def assert_readable_error(status: int, body, *, expect_status: int, contains: str) -> None:
    assert status == expect_status, (status, body)
    assert isinstance(body, dict) and isinstance(body.get("error"), str), body
    assert contains in body["error"], body["error"]


# ── create task ──────────────────────────────────────────────────────────────


def test_console_create_task_succeeds_and_is_listed(door):
    status, body = request(door, "POST", f"/api/projects/{PROJECT}/work-items", task_body())
    assert status == 200, body
    assert body["status"] == "filed"
    row = body["row"]
    assert row["external_id"] == "wi-1760000000000-abc123"
    assert row["project_code"] == PROJECT
    assert row["name"] == "Write the onboarding email"
    assert row["type"] == "task"
    assert row["state"] == "ready"
    assert row["description"] == "Draft the welcome email new users get after install."
    assert row["acceptance_criteria"].startswith("The draft email is saved")

    status, rows = request(door, "GET", f"/api/projects/{PROJECT}/work-items")
    assert status == 200
    assert [r["external_id"] for r in rows] == ["wi-1760000000000-abc123"]


def test_console_create_task_without_optional_text_succeeds(door):
    status, body = request(door, "POST", f"/api/projects/{PROJECT}/work-items", task_body(
        description=None, acceptance_criteria=None,
    ))
    assert status == 200, body
    assert body["row"]["acceptance_criteria"] is None


def test_console_create_task_in_a_module_under_a_parent_with_docs(door):
    request(door, "POST", f"/api/projects/{PROJECT}/modules", module_body())
    status, parent = request(door, "POST", f"/api/projects/{PROJECT}/work-items", task_body())
    assert status == 200, parent
    status, child = request(door, "POST", f"/api/projects/{PROJECT}/work-items", task_body(
        external_id="wi-1760000000009-sub001",
        name="Subtask",
        module="mod-1760000000001-ghi789",
        parent_work_item="wi-1760000000000-abc123",
        source_references=[{"uri": "docs/welcome.md"}],
    ))
    assert status == 200, child
    row = child["row"]
    assert row["module_id"] is not None
    assert row["parent_work_item_id"] == parent["row"]["id"]
    assert row["source_references"] == [{"uri": "docs/welcome.md", "anchor": None}]


def test_console_create_task_in_state_done_is_stamped_as_the_console(door):
    status, body = request(door, "POST", f"/api/projects/{PROJECT}/work-items", task_body(state="done"))
    assert status == 200, body
    assert body["row"]["state"] == "done"
    assert body["row"]["completed_by"] == "hyperspace-console"
    assert body["row"]["completed_at"] is not None


def test_console_create_task_forced_failures_say_why(door):
    path = f"/api/projects/{PROJECT}/work-items"
    status, body = request(door, "POST", path, task_body(acceptance_criteria="too short"))
    assert_readable_error(status, body, expect_status=400, contains="acceptance_criteria must be 20-2000 characters (got 9)")

    status, body = request(door, "POST", path, task_body(name="   "))
    assert_readable_error(status, body, expect_status=400, contains="name must be a non-empty string")

    status, body = request(door, "POST", path, task_body(state="finished"))
    assert_readable_error(status, body, expect_status=400, contains="invalid state: 'finished'")

    status, body = request(door, "POST", path, task_body(type="chore"))
    assert_readable_error(status, body, expect_status=400, contains="invalid type: 'chore'")

    status, body = request(door, "POST", path, task_body(module="no-such-module"))
    assert_readable_error(status, body, expect_status=404, contains="module not found: 'no-such-module'")

    status, body = request(door, "POST", path, task_body(parent_work_item="no-such-parent"))
    assert_readable_error(status, body, expect_status=404, contains="parent work item not found: 'no-such-parent'")

    status, body = request(door, "POST", path, task_body(surprise=1))
    assert_readable_error(status, body, expect_status=400, contains="unknown fields: surprise")

    status, rows = request(door, "GET", path)
    assert rows == [], "a refused create writes nothing"


def test_console_create_in_an_unknown_project_says_so(door):
    for kind, body in (
        ("work-items", task_body()), ("modules", module_body()), ("cycles", cycle_body()),
    ):
        status, got = request(door, "POST", f"/api/projects/nope/{kind}", body)
        assert_readable_error(status, got, expect_status=404, contains="project not found: 'nope'")


def test_agent_door_still_requires_the_full_proposal(fresh_db):
    """The agent's `upsert_work_item` contract is untouched: the console's flat
    row is not a proposal, and the agent door refuses it."""
    store = Store.open(fresh_db)
    try:
        result = call_tool(store, "upsert_work_item", {"project": PROJECT, **task_body()})
    finally:
        store.close()
    assert result["error"]["code"] == "validation"
    assert "specification" in result["error"]["message"]


# ── create module / cycle / initiative ───────────────────────────────────────


def test_console_create_module_succeeds_and_is_listed(door):
    status, row = request(door, "POST", f"/api/projects/{PROJECT}/modules", module_body())
    assert status == 200, row
    assert row["external_id"] == "mod-1760000000001-ghi789"
    assert row["project_code"] == PROJECT
    assert row["name"] == "Onboarding"
    assert row["state"] == "pending-review"
    assert row["acceptance_criteria"].startswith("Every onboarding task is done")

    status, rows = request(door, "GET", f"/api/projects/{PROJECT}/modules")
    assert [r["external_id"] for r in rows] == ["mod-1760000000001-ghi789"]


def test_console_create_module_forced_failures_say_why(door):
    path = f"/api/projects/{PROJECT}/modules"
    status, body = request(door, "POST", path, module_body(acceptance_criteria="nope"))
    assert_readable_error(status, body, expect_status=400, contains="acceptance_criteria must be 20-2000 characters (got 4)")

    status, body = request(door, "POST", path, module_body(name=""))
    assert_readable_error(status, body, expect_status=400, contains="name is required")

    status, body = request(door, "POST", path, module_body(surprise=1))
    assert_readable_error(status, body, expect_status=400, contains="unknown fields: surprise")

    status, body = request(door, "POST", path, module_body(state="finished"))
    assert_readable_error(status, body, expect_status=400, contains="state='finished' is not one of")

    status, rows = request(door, "GET", path)
    assert rows == []


def test_console_create_cycle_succeeds_and_is_listed(door):
    status, row = request(door, "POST", f"/api/projects/{PROJECT}/cycles", cycle_body())
    assert status == 200, row
    assert row["external_id"] == "cy-1760000000002-mno345"
    assert row["name"] == "Week 1"
    assert row["state"] == "planned"

    status, rows = request(door, "GET", f"/api/projects/{PROJECT}/cycles")
    assert [r["external_id"] for r in rows] == ["cy-1760000000002-mno345"]


def test_console_create_cycle_without_a_name_says_why(door):
    status, body = request(door, "POST", f"/api/projects/{PROJECT}/cycles", cycle_body(name=None))
    assert_readable_error(status, body, expect_status=400, contains="name is required")


def test_console_create_initiative_then_archive_it_then_link_it(door):
    status, row = request(door, "POST", "/api/initiatives", initiative_body())
    assert status == 200, row
    assert row["title"] == "Launch"
    assert row["state"] == "planned"

    # The archive the console sends: only `state`. The title is kept.
    status, row = request(door, "PATCH", "/api/initiatives/init-1760000000003-stu901", {"state": "archived"})
    assert status == 200, row
    assert row["state"] == "archived" and row["title"] == "Launch"

    # An edit: the keys the drawer sends.
    status, row = request(door, "PATCH", "/api/initiatives/init-1760000000003-stu901", {
        "title": "Launch v2", "description": "Ship it.", "doc_paths": ["docs/launch.md"],
    })
    assert status == 200, row
    assert (row["title"], row["description"], row["doc_paths"]) == ("Launch v2", "Ship it.", ["docs/launch.md"])

    # The link: keyed by the initiative's row id, one target per call.
    initiative_id = row["id"]
    for link_type, target in (("project", PROJECT), ("module", "mod-x"), ("work_item", "wi-x")):
        status, got = request(door, "POST", f"/api/initiatives/{initiative_id}/links", {
            "link_type": link_type, "target_id": target,
        })
        assert status == 200, got
    status, links = request(door, "GET", f"/api/initiatives/{initiative_id}/links")
    assert sorted((l["link_type"], l["target"]) for l in links) == [
        ("module", "mod-x"), ("project", PROJECT), ("work_item", "wi-x"),
    ]


def test_console_initiative_forced_failures_say_why(door):
    status, body = request(door, "POST", "/api/initiatives", initiative_body(title=""))
    assert_readable_error(status, body, expect_status=400, contains="title is required")

    status, body = request(door, "PATCH", "/api/initiatives/nope", {"state": "archived"})
    assert_readable_error(status, body, expect_status=404, contains="initiative not found: 'nope'")

    request(door, "POST", "/api/initiatives", initiative_body())
    status, body = request(door, "PATCH", "/api/initiatives/init-1760000000003-stu901", {})
    assert_readable_error(status, body, expect_status=400, contains="at least one mutable field is required")

    status, body = request(door, "PATCH", "/api/initiatives/init-1760000000003-stu901", {"colour": "red"})
    assert_readable_error(status, body, expect_status=400, contains="unknown or immutable fields: colour")

    status, body = request(door, "POST", "/api/initiatives/init-1760000000003-stu901/links", {
        "link_type": "cycle", "target_id": "x",
    })
    assert_readable_error(status, body, expect_status=400, contains="link_type must be one of")

    status, body = request(door, "POST", "/api/initiatives/nope/links", {"link_type": "project", "target_id": "x"})
    assert_readable_error(status, body, expect_status=404, contains="initiative not found: 'nope'")


# ── writes the engine does not serve say so ──────────────────────────────────


def test_unserved_console_writes_fail_with_a_readable_cause(door):
    status, body = request(door, "POST", "/api/work-items/wi-1/promote-to-module", {
        "module_name": "Promoted", "idempotency_key": "idem-x",
    })
    assert_readable_error(status, body, expect_status=501, contains="promoting a task to a module")

    status, body = request(door, "DELETE", "/api/initiatives/some-id/links/project/some-code")
    assert_readable_error(status, body, expect_status=501, contains="unlinking")


def test_bad_write_requests_are_json_errors_not_html(door):
    status, body = request(door, "POST", f"/api/projects/{PROJECT}/work-items", raw=b"{not json")
    assert_readable_error(status, body, expect_status=400, contains="request body must be a JSON object")

    status, body = request(door, "POST", f"/api/projects/{PROJECT}/work-items", ["not", "an", "object"])
    assert_readable_error(status, body, expect_status=400, contains="request body must be a JSON object")

    status, body = request(door, "POST", "/api/does-not-exist", {})
    assert_readable_error(status, body, expect_status=404, contains="not found: /api/does-not-exist")

    status, body = request(door, "DELETE", "/api/does-not-exist")
    assert_readable_error(status, body, expect_status=404, contains="not found: /api/does-not-exist")


def test_existing_writes_still_work(door):
    """`/mcp` and the work-item PATCH were served before this row."""
    status, body = request(door, "POST", f"/api/projects/{PROJECT}/work-items", task_body())
    assert status == 200
    status, body = request(door, "PATCH", "/api/work-items/wi-1760000000000-abc123", {"name": "Renamed"})
    assert status == 200 and body["row"]["name"] == "Renamed"
    status, body = request(door, "POST", "/mcp", {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "upsert_project", "arguments": {"code": "second", "name": "Second"}},
    })
    assert status == 200 and "result" in body


def mcp_call(door: Door, name: str, arguments: dict):
    """`mcpCall` in App.tsx: the JSON-RPC envelope, the tool's text unwrapped."""
    status, body = request(door, "POST", "/mcp", {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments},
    })
    assert status == 200, body
    result = body["result"]
    text = result["content"][0]["text"]
    assert not result.get("isError"), text
    return json.loads(text)


def test_console_writes_sent_over_mcp_are_served(door):
    """The project create and edit, and assigning a task to a cycle, are
    `tools/call`s over `/mcp` (not REST) — served before this row, kept served."""
    created = mcp_call(door, "upsert_project", {
        "code": "second-project-uuid", "name": "Second project", "description": "d",
        "folder_path": "notes", "status": "planned", "team": ["user"],
    })
    assert created["name"] == "Second project" and created["folder_path"] == "notes"
    edited = mcp_call(door, "upsert_project", {"code": "second-project-uuid", "name": "Renamed", "owner": "user"})
    assert (edited["name"], edited["owner"], edited["description"]) == ("Renamed", "user", "d")

    request(door, "POST", f"/api/projects/{PROJECT}/work-items", task_body())
    request(door, "POST", f"/api/projects/{PROJECT}/cycles", cycle_body())
    assigned = mcp_call(door, "assign_cycle_work_items", {
        "project": PROJECT, "cycle": "cy-1760000000002-mno345",
        "work_items": ["wi-1760000000000-abc123"], "idempotency_key": "cyassign-1",
    })
    assert assigned["work_items"] == ["wi-1760000000000-abc123"]


def test_a_console_write_the_tool_refuses_comes_back_as_its_own_message(door):
    """Over `/mcp` a refused write is `isError` with the tool's message in the text."""
    status, body = request(door, "POST", "/mcp", {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "assign_cycle_work_items", "arguments": {
            "project": PROJECT, "cycle": "no-such-cycle", "work_items": [], "idempotency_key": "x",
        }},
    })
    assert status == 200
    assert body["result"]["isError"] is True
    assert body["result"]["content"][0]["text"] == "cycle not found: 'no-such-cycle'"


# ── GET /api/worklog ─────────────────────────────────────────────────────────


def _seed_worklog(db_path: Path) -> None:
    store = Store.open(db_path)
    try:
        call_tool(store, "upsert_project", {"code": "other", "name": "Other"})
        store.append_worklog(
            author="user", summary="first", project=PROJECT, tags=["a"],
            detailed="the long version", created_at="2026-10-01T10:00:00+00:00",
        )
        store.append_worklog(
            author="probe", summary="second", project="other", created_at="2026-10-02T10:00:00+00:00",
        )
        store.append_worklog(
            author="user", summary="third", project=PROJECT, tags=["b", "c"],
            created_at="2026-10-03T10:00:00+00:00",
        )
    finally:
        store.close()


def test_worklog_lists_every_entry_newest_first_with_its_fields(door, fresh_db):
    _seed_worklog(fresh_db)
    status, rows = request(door, "GET", "/api/worklog")
    assert status == 200
    assert [r["summary"] for r in rows] == ["third", "second", "first"]
    first = rows[2]
    for field in ("id", "created_at", "author", "summary", "tags", "project", "detailed"):
        assert field in first, field
    assert first["tags"] == ["a"] and first["detailed"] == "the long version"
    assert first["author"] == "user" and first["project"] == PROJECT


def test_worklog_filters_by_project(door, fresh_db):
    _seed_worklog(fresh_db)
    status, rows = request(door, "GET", f"/api/worklog?project={PROJECT}")
    assert status == 200
    assert [r["summary"] for r in rows] == ["third", "first"]
    status, rows = request(door, "GET", "/api/worklog?project=nothing-here")
    assert status == 200 and rows == []


def test_worklog_blank_project_means_all(door, fresh_db):
    _seed_worklog(fresh_db)
    status, rows = request(door, "GET", "/api/worklog?project=")
    assert status == 200 and len(rows) == 3


# ── GET /api/projects/<code>/runs ────────────────────────────────────────────


def _write_run(root: Path, slug: str, **state) -> None:
    run_dir = root / "hyperspace" / "runs" / slug
    run_dir.mkdir(parents=True)
    (run_dir / "loop.state.json").write_text(json.dumps({"goal_slug": slug, **state}), encoding="utf-8")


def test_runs_lists_every_run_with_open_marked(door, fresh_db):
    root = fresh_db.parent.parent
    _write_run(root, "build-the-thing", status="deciding", current_node="deciding")
    _write_run(root, "ship-it", status="live", current_node="executing")
    _write_run(root, "old-one", status="done", current_node="executing")
    _write_run(root, "dropped", status="killed", current_node="deciding")
    _write_run(root, "set-aside", status="descoped", current_node="understanding")

    status, runs = request(door, "GET", f"/api/projects/{PROJECT}/runs")
    assert status == 200
    by_goal = {r["goal"]: r for r in runs}
    assert set(by_goal) == {"build-the-thing", "ship-it", "old-one", "dropped", "set-aside"}
    assert by_goal["build-the-thing"] == {
        "goal": "build-the-thing", "status": "deciding", "current_node": "deciding",
        "run_folder": "hyperspace/runs/build-the-thing", "open": True,
    }
    assert by_goal["ship-it"]["open"] is True and by_goal["ship-it"]["status"] == "live"
    assert by_goal["old-one"]["open"] is False
    assert by_goal["dropped"]["open"] is False
    assert by_goal["set-aside"]["open"] is False


def test_runs_open_one_and_closed_one_fixture(door, fresh_db):
    root = fresh_db.parent.parent
    _write_run(root, "open-run", status="executing", current_node="executing")
    _write_run(root, "closed-run", status="done", current_node="executing")
    status, runs = request(door, "GET", f"/api/projects/{PROJECT}/runs")
    assert [(r["goal"], r["open"]) for r in runs] == [("closed-run", False), ("open-run", True)]


def test_runs_with_no_runs_folder_is_an_empty_list(door):
    status, runs = request(door, "GET", f"/api/projects/{PROJECT}/runs")
    assert status == 200 and runs == []


def test_runs_skips_a_state_file_it_cannot_read(door, fresh_db):
    root = fresh_db.parent.parent
    _write_run(root, "good", status="deciding", current_node="deciding")
    broken = root / "hyperspace" / "runs" / "broken"
    broken.mkdir(parents=True)
    (broken / "loop.state.json").write_text("{not json", encoding="utf-8")
    status, runs = request(door, "GET", f"/api/projects/{PROJECT}/runs")
    assert status == 200 and [r["goal"] for r in runs] == ["good"]


def test_runs_for_an_unknown_project_says_so(door):
    status, body = request(door, "GET", "/api/projects/nope/runs")
    assert_readable_error(status, body, expect_status=404, contains="project not found: 'nope'")


def test_terminal_set_is_the_one_loop_state_defines():
    """The door cannot import `bin/` (the wheel installed into a user's
    `.hyperspace/env` carries `hyperspace/` and `ui/dist` only), so it holds a
    copy of the terminal set. This is what keeps the copy honest."""
    import loop_terminal

    from hyperspace.http.runs import TERMINAL_STATUSES

    schema = json.loads((BIN / "loop_state.schema.json").read_text(encoding="utf-8"))
    schema_terminal = set(schema["properties"]["final_route"]["enum"]) - {None}
    assert TERMINAL_STATUSES == set(loop_terminal.LEGITIMATE_TERMINAL) == schema_terminal
