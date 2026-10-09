"""tests/test_http.py — the loopback door (row T4.2): the console's REST
reads answered from the store, its JSON-RPC writes routed through the
graph-tool table, the prebuilt page served, all bound to 127.0.0.1 only.
"""
from __future__ import annotations

import argparse
import json
from http.client import HTTPConnection

import pytest

from hyperspace.cli import _prepare_serve
from hyperspace.http.server import Door, create_door, start, _static_dir
from hyperspace.store import Store
from hyperspace.tools import call_tool


def _candidate(**overrides) -> dict:
    payload = {
        "project": "demo-project",
        "external_id": "demo-project:wi-1",
        "name": "Do the thing",
        "type": "task",
        "state": None,
        "parent_work_item": None,
        "assignee_agent": None,
        "team": None,
        "idempotency_key": "wi-1-create",
        "specification": {
            "problem": "The loopback door has no tests yet, so nothing proves the console's contract is served.",
            "why_it_matters": "Without the door the console cannot read or write anything against a real store.",
            "context_pointer": "brief.md step 2, hsp-loopback-http-door row.",
        },
        "source_references": [{"uri": "worklog entry deadbeef"}],
        "effort_level": "medium",
        "module": None,
        "acceptance_criteria": [
            {
                "statement": "The HTTP door's contract check passes.",
                "verification": {"kind": "command_check", "check_id": "tests"},
            }
        ],
        "proposer_identity": "engineer",
        "proposer_surface": "cli-mac",
        "uncertainty_notes": [],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def seeded_store_path(tmp_path):
    """One project, one module, one work item, one cycle, one initiative,
    one worklog entry — every one seeded through `call_tool` (brief step 2)."""
    db_path = tmp_path / ".hyperspace" / "graph.db"
    store = Store.init(db_path)

    call_tool(store, "upsert_project", {"code": "demo-project", "name": "Demo Project"})
    call_tool(store, "upsert_module", {
        "project": "demo-project", "external_id": "demo-project:mod-1", "name": "Demo Module",
        "acceptance_criteria": "Every work item under this module reaches done.",
    })
    wi_result = call_tool(store, "upsert_work_item", _candidate())
    call_tool(store, "upsert_cycle", {
        "project": "demo-project", "external_id": "demo-project:cy-1", "name": "Cycle One",
    })
    call_tool(store, "upsert_initiative", {"external_id": "demo-init", "title": "Demo Initiative"})
    call_tool(store, "link_initiative_objects", {
        "initiative": "demo-init", "projects": ["demo-project"],
    })
    call_tool(store, "append_worklog", {
        "author": "engineer", "project": "demo-project", "summary": "Seeded the door's test store.",
    })
    store.close()

    return db_path, wi_result["row"]


@pytest.fixture
def running_door(seeded_store_path):
    db_path, _seed_row = seeded_store_path
    door = start(db_path, port=0)
    try:
        yield door
    finally:
        door.shutdown()
        door.server_close()


def _get(door: Door, path: str, headers: dict | None = None):
    conn = HTTPConnection(door.server_address[0], door.server_address[1])
    try:
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, resp.getheader("Content-Type"), body
    finally:
        conn.close()


def _post_mcp(door: Door, payload, headers: dict | None = None):
    conn = HTTPConnection(door.server_address[0], door.server_address[1])
    try:
        body = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
        if isinstance(body, str):
            body = body.encode("utf-8")
        conn.request(
            "POST", "/mcp", body=body,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())
    finally:
        conn.close()


# ── reads ────────────────────────────────────────────────────────────────


def test_get_projects(running_door):
    status, ctype, body = _get(running_door, "/api/projects")
    assert status == 200
    assert ctype == "application/json"
    rows = json.loads(body)
    assert any(r["code"] == "demo-project" for r in rows)


def test_get_project_work_items_modules_cycles(running_door):
    for kind in ("work-items", "modules", "cycles"):
        status, _ctype, body = _get(running_door, f"/api/projects/demo-project/{kind}")
        assert status == 200, f"{kind}: {body}"
        rows = json.loads(body)
        assert isinstance(rows, list) and len(rows) == 1, f"{kind}: {rows}"


def test_get_module_by_uuid_and_external_id(running_door):
    _status, _ctype, body = _get(running_door, "/api/projects/demo-project/modules")
    module_row = json.loads(body)[0]

    status, _ctype, body = _get(running_door, f"/api/modules/{module_row['id']}")
    assert status == 200
    assert json.loads(body)["external_id"] == "demo-project:mod-1"

    status, _ctype, body = _get(running_door, f"/api/modules/{module_row['external_id']}")
    assert status == 200
    assert json.loads(body)["id"] == module_row["id"]


def test_get_work_item_by_uuid_and_external_id(running_door, seeded_store_path):
    _db_path, seed_row = seeded_store_path

    status, _ctype, body = _get(running_door, f"/api/work-items/{seed_row['id']}")
    assert status == 200
    assert json.loads(body)["external_id"] == "demo-project:wi-1"

    status, _ctype, body = _get(running_door, f"/api/work-items/{seed_row['external_id']}")
    assert status == 200
    assert json.loads(body)["id"] == seed_row["id"]


def test_get_initiatives_and_item(running_door):
    status, _ctype, body = _get(running_door, "/api/initiatives")
    assert status == 200
    rows = json.loads(body)
    assert any(r["external_id"] == "demo-init" for r in rows)

    status, _ctype, body = _get(running_door, "/api/initiatives/demo-init")
    assert status == 200
    assert json.loads(body)["title"] == "Demo Initiative"


def test_get_initiative_links(running_door):
    _status, _ctype, body = _get(running_door, "/api/initiatives")
    init_row = next(r for r in json.loads(body) if r["external_id"] == "demo-init")

    status, _ctype, body = _get(running_door, f"/api/initiatives/{init_row['id']}/links")
    assert status == 200
    links = json.loads(body)
    assert any(link["link_type"] == "project" and link["target"] == "demo-project" for link in links)


def test_unknown_api_route_is_404_json(running_door):
    status, ctype, body = _get(running_door, "/api/nope")
    assert status == 404
    assert ctype == "application/json"
    assert "error" in json.loads(body)


def test_bearer_header_changes_nothing_on_reads(running_door):
    plain = _get(running_door, "/api/projects")
    with_bearer = _get(running_door, "/api/projects", headers={"Authorization": "Bearer x"})
    assert plain[0] == with_bearer[0] == 200
    assert plain[2] == with_bearer[2]


# ── writes (JSON-RPC over /mcp) ─────────────────────────────────────────


def test_mcp_get_recent_activity(running_door):
    status, data = _post_mcp(running_door, {
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "get_recent_activity", "arguments": {"limit": 5}},
    })
    assert status == 200
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 7
    assert "isError" not in data["result"]
    entries = json.loads(data["result"]["content"][0]["text"])
    assert any(e["summary"] == "Seeded the door's test store." for e in entries)


def test_mcp_append_worklog(running_door):
    status, data = _post_mcp(running_door, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "append_worklog", "arguments": {
            "author": "engineer", "project": "demo-project", "summary": "via /mcp",
        }},
    })
    assert status == 200
    row = json.loads(data["result"]["content"][0]["text"])
    assert row["summary"] == "via /mcp"


def test_mcp_list_agents(running_door):
    status, data = _post_mcp(running_door, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "list_agents", "arguments": {}},
    })
    assert status == 200
    agents = json.loads(data["result"]["content"][0]["text"])
    assert isinstance(agents, list) and len(agents) == 1


def test_mcp_upsert_work_item(running_door):
    status, data = _post_mcp(running_door, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "upsert_work_item", "arguments": _candidate(
            external_id="demo-project:wi-2", idempotency_key="wi-2-create",
        )},
    })
    assert status == 200
    result = json.loads(data["result"]["content"][0]["text"])
    assert result["status"] == "filed"
    assert result["row"]["external_id"] == "demo-project:wi-2"


def _call_upsert(door, arguments: dict, req_id: int = 10):
    status, data = _post_mcp(door, {
        "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
        "params": {"name": "upsert_work_item", "arguments": arguments},
    })
    assert status == 200
    return data["result"]


def test_mcp_upsert_work_item_create_done_closes_as_console(running_door):
    """The console's HTTP door is the one door that still accepts a person's
    `state="done"` — stamped `hyperspace-console`, readable back over GET."""
    result = _call_upsert(running_door, _candidate(
        external_id="demo-project:wi-done", idempotency_key="wi-done-create", state="done",
    ))
    assert "isError" not in result
    row = json.loads(result["content"][0]["text"])["row"]
    assert row["state"] == "done"
    assert row["completed_by"] == "hyperspace-console"

    status, _ctype, body = _get(running_door, f"/api/work-items/{row['id']}")
    assert status == 200
    assert json.loads(body)["completed_by"] == "hyperspace-console"


def test_mcp_upsert_work_item_update_done_closes_as_console(running_door, seeded_store_path):
    _db, seed_row = seeded_store_path  # `demo-project:wi-1`, filed with state=None
    result = _call_upsert(running_door, _candidate(idempotency_key="wi-1-done", state="done"))
    assert "isError" not in result
    row = json.loads(result["content"][0]["text"])["row"]
    assert row["id"] == seed_row["id"]
    assert row["state"] == "done"
    assert row["completed_by"] == "hyperspace-console"


def test_mcp_door_label_cannot_be_chosen_by_the_request_body(running_door):
    for field, value in (("completed_by", "hyperspace-verifier"), ("console", False), ("door", "agent")):
        result = _call_upsert(running_door, {**_candidate(
            external_id="demo-project:wi-spoof", idempotency_key="wi-spoof-create", state="done",
        ), field: value})
        assert result["isError"] is True, field
    status, _ctype, _body = _get(running_door, "/api/work-items/demo-project:wi-spoof")
    assert status == 404


# ── PATCH /api/work-items/<id> — the console closes a task ────────────────
#
# The request bodies below are the ones the pinned console bundle sends
# (`ui/dist`, Caelos dfcb46d; tests/test_ui_bundle.py checks the key set
# against the bundle itself): partial, ops-server key names (`module`,
# `parent_work_item`, `assignee_agent`), the id in the URL being the row's
# external_id (or its uuid).

WI = "demo-project:wi-1"


def _patch(door: Door, path: str, payload, headers: dict | None = None):
    conn = HTTPConnection(door.server_address[0], door.server_address[1])
    try:
        body = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
        if isinstance(body, str):
            body = body.encode("utf-8")
        conn.request("PATCH", path, body=body, headers={"Content-Type": "application/json", **(headers or {})})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())
    finally:
        conn.close()


def _row(door: Door, ident: str = WI) -> dict:
    status, _ctype, body = _get(door, f"/api/work-items/{ident}")
    assert status == 200
    return json.loads(body)


def test_console_patch_state_done_closes_as_console(running_door):
    status, data = _patch(running_door, f"/api/work-items/{WI}", {"state": "done"})
    assert status == 200
    assert data["status"] == "updated"
    assert data["row"]["state"] == "done"
    assert data["row"]["completed_by"] == "hyperspace-console"
    assert data["row"]["completed_at"]
    assert _row(running_door)["completed_by"] == "hyperspace-console"


def test_console_patch_resolves_uuid_and_percent_encoded_ids(running_door, seeded_store_path):
    _db, seed_row = seeded_store_path
    status, data = _patch(running_door, f"/api/work-items/{seed_row['id']}", {"state": "in-progress"})
    assert status == 200 and data["row"]["state"] == "in-progress"
    # the page encodes ids with encodeURIComponent: the colon arrives as %3A
    status, data = _patch(running_door, "/api/work-items/demo-project%3Awi-1", {"state": "done"})
    assert status == 200 and data["row"]["completed_by"] == "hyperspace-console"
    assert _row(running_door, "demo-project%3Awi-1")["state"] == "done"


def test_console_patch_reopening_clears_the_stamp(running_door):
    _patch(running_door, f"/api/work-items/{WI}", {"state": "done"})
    status, data = _patch(running_door, f"/api/work-items/{WI}", {"state": "ready"})
    assert status == 200
    assert data["row"]["state"] == "ready"
    assert data["row"]["completed_by"] is None and data["row"]["completed_at"] is None


def test_console_patch_never_rewrites_the_door_that_closed_a_row(running_door, seeded_store_path):
    db_path, seed_row = seeded_store_path
    store = Store.open(db_path)
    try:
        store.set_work_item_state(seed_row["id"], "done", completed_by="hyperspace-verifier")
    finally:
        store.close()
    # an edit that resends the same state, and an edit that does not mention it
    for body in ({"state": "done"}, {"name": "Renamed by the console"}):
        status, data = _patch(running_door, f"/api/work-items/{WI}", body)
        assert status == 200
        assert data["row"]["completed_by"] == "hyperspace-verifier", body
    assert data["row"]["name"] == "Renamed by the console"


def test_console_patch_sets_only_the_keys_sent(running_door):
    before = _row(running_door)
    status, data = _patch(running_door, f"/api/work-items/{WI}", {
        "name": "New name", "description": "New description",
        "acceptance_criteria": "Every check in the suite passes on the target.",
        "acceptance_criteria_ref": "docs/criteria.md", "assignee_agent": "engineer",
        "team": ["engineer", "designer"], "position": 1.5,
        "module": "demo-project:mod-1", "parent_work_item": None, "project": "demo-project",
        "source_references": [{"uri": "docs/a.md", "anchor": "top"}, {"uri": "docs/b.md"}],
    })
    assert status == 200, data
    row = data["row"]
    assert (row["name"], row["description"], row["assignee_agent"]) == ("New name", "New description", "engineer")
    assert row["team"] == ["engineer", "designer"] and row["position"] == 1.5
    assert row["source_references"] == [{"uri": "docs/a.md", "anchor": "top"}, {"uri": "docs/b.md", "anchor": None}]
    assert row["module_id"] is not None and row["parent_work_item_id"] is None
    # untouched: state, type, filing key
    assert (row["state"], row["type"], row["idempotency_key"]) == (before["state"], before["type"], before["idempotency_key"])


@pytest.mark.parametrize("body, status_code, fragment", [
    ({}, 400, "at least one mutable field"),
    ({"completed_by": "hyperspace-verifier"}, 400, "unknown or immutable fields: completed_by"),
    ({"state": "done", "closure_label": "x"}, 400, "closure_label"),
    ({"state": "finished"}, 400, "invalid state"),
    ({"name": "  "}, 400, "name must be"),
    ({"team": "engineer"}, 400, "team must be a list"),
    ({"position": "first"}, 400, "position must be a number"),
    ({"source_references": [{"anchor": "no uri"}]}, 400, "source_references"),
    ({"project": "another-project"}, 400, "another project"),
    ({"parent_work_item": WI}, 400, "its own parent"),
    ({"module": "demo-project:nope"}, 404, "module not found"),
    ({"parent_work_item": "demo-project:nope"}, 404, "parent work item not found"),
])
def test_console_patch_refusals_write_nothing(running_door, body, status_code, fragment):
    before = _row(running_door)
    status, data = _patch(running_door, f"/api/work-items/{WI}", body)
    assert status == status_code, data
    assert fragment in data["error"]
    after = _row(running_door)
    assert {k: v for k, v in after.items() if k != "updated_at"} == {k: v for k, v in before.items() if k != "updated_at"}


def test_console_patch_cannot_clear_set_criteria_but_null_to_null_is_legal(running_door):
    _patch(running_door, f"/api/work-items/{WI}", {"acceptance_criteria": "Every check in the suite passes."})
    status, data = _patch(running_door, f"/api/work-items/{WI}", {"acceptance_criteria": None})
    assert status == 400 and "cannot be cleared" in data["error"]


def test_console_patch_unknown_row_and_bad_bodies(running_door):
    assert _patch(running_door, "/api/work-items/demo-project:missing", {"state": "done"})[0] == 404
    assert _patch(running_door, f"/api/work-items/{WI}", b"not json")[0] == 400
    assert _patch(running_door, f"/api/work-items/{WI}", ["state", "done"])[0] == 400
    assert _patch(running_door, "/api/modules/demo-project:mod-1", {"state": "done"})[0] == 404


def test_console_patch_closes_a_row_the_mcp_tool_refuses_to_close(running_door, seeded_store_path):
    """The two doors side by side: the MCP tool's agent door refuses `done`,
    the console's PATCH closes the same row under its own label."""
    db_path, _seed = seeded_store_path
    store = Store.open(db_path)
    try:
        refused = call_tool(store, "upsert_work_item", _candidate(state="done", idempotency_key="wi-1-agent-done"))
        assert refused["error"]["code"] == "refused"
        assert store.get_work_item(external_id=WI, project_code="demo-project")["state"] != "done"
    finally:
        store.close()
    status, data = _patch(running_door, f"/api/work-items/{WI}", {"state": "done"})
    assert status == 200 and data["row"]["completed_by"] == "hyperspace-console"


def test_mcp_tool_error_is_iserror(running_door):
    # Missing acceptance_criteria -> ToolError("validation", ...) inside
    # call_tool, which call_tool itself wraps into {"error": {...}} —
    # route_mcp's job is turning THAT into the console's isError shape.
    bad = _candidate(external_id="demo-project:wi-bad", idempotency_key="wi-bad-create")
    del bad["acceptance_criteria"]
    status, data = _post_mcp(running_door, {
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "upsert_work_item", "arguments": bad},
    })
    assert status == 200
    assert data["result"]["isError"] is True
    assert isinstance(data["result"]["content"][0]["text"], str)


def test_mcp_malformed_body_is_json_rpc_error(running_door):
    status, data = _post_mcp(running_door, b"not json at all")
    assert status == 200
    assert data["error"]["code"] == -32600


def test_mcp_bearer_header_changes_nothing(running_door):
    payload = {
        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"name": "list_agents", "arguments": {}},
    }
    plain = _post_mcp(running_door, payload)
    with_bearer = _post_mcp(running_door, payload, headers={"Authorization": "Bearer x"})
    assert plain == with_bearer


# ── static / SPA ─────────────────────────────────────────────────────────


def test_index_served_at_root(running_door):
    status, ctype, body = _get(running_door, "/")
    assert status == 200
    assert ctype.startswith("text/html")
    lowered = body.lower()
    assert b"<html" in lowered or b"<!doctype" in lowered


def test_unknown_asset_returns_404(running_door):
    status, _ctype, _body = _get(running_door, "/assets/does-not-exist.js")
    assert status == 404


def test_known_asset_served_with_content_type(running_door):
    static_dir = _static_dir()
    asset_files = [p for p in (static_dir / "assets").iterdir() if p.is_file()]
    assert asset_files, "expected at least one built asset in ui/dist/assets"
    js_or_css = next((p for p in asset_files if p.suffix in (".js", ".css")), asset_files[0])

    status, ctype, body = _get(running_door, f"/assets/{js_or_css.name}")
    assert status == 200
    assert ctype is not None
    assert body == js_or_css.read_bytes()


def test_unknown_non_api_path_falls_back_to_index(running_door):
    status, ctype, body = _get(running_door, "/some/console/route")
    assert status == 200
    assert ctype.startswith("text/html")

    _root_status, _root_ctype, root_body = _get(running_door, "/")
    assert body == root_body


# ── binding discipline ───────────────────────────────────────────────────


def test_door_binds_127_0_0_1(running_door):
    assert running_door.server_address[0] == "127.0.0.1"


def test_door_refuses_non_loopback_host(tmp_path):
    db_path = tmp_path / ".hyperspace" / "graph.db"
    Store.init(db_path).close()
    with pytest.raises(ValueError):
        create_door(db_path, host="0.0.0.0", port=0)


def test_second_server_on_same_port_is_rejected(seeded_store_path):
    db_path, _seed_row = seeded_store_path
    project_dir = db_path.parent.parent

    first = create_door(db_path, port=0)
    try:
        busy_port = first.server_address[1]
        args = argparse.Namespace(rest=["--port", str(busy_port), "--dir", str(project_dir)])
        result = _prepare_serve(args)
        assert result == 1
    finally:
        # `first` was only ever bound (never `serve_forever()`-ed) — `.shutdown()`
        # blocks forever waiting for an event only the serve_forever loop sets;
        # `.server_close()` alone is what actually frees the port here.
        first.server_close()


def test_serve_open_calls_opener_with_door_url(seeded_store_path):
    db_path, _seed_row = seeded_store_path
    project_dir = db_path.parent.parent
    calls = []

    args = argparse.Namespace(rest=["--port", "0", "--open", "--dir", str(project_dir)])
    result = _prepare_serve(args, opener=calls.append)
    assert not isinstance(result, int), f"expected a Door, got exit code {result}"
    door = result
    try:
        assert len(calls) == 1
        assert calls[0] == f"http://127.0.0.1:{door.server_address[1]}/"
    finally:
        door.server_close()
