"""T2.2 — the graph tools: one function table over the store.

Covers: a typed result from each of the seventeen tools against a temporary
store; `upsert_work_item` refuses a candidate with no acceptance criteria and
one with placeholder text (no row written either way); a criteria update
with `update_acceptance_criteria: true` and the ORIGINAL idempotency_key
mints a fresh filing under a fresh key (S2), leaving the first filing
unchanged and re-pointing the row's ref; the same call WITHOUT the flag is
refused `conflict`; a repeat call with the same key and unchanged payload is
idempotent; `get_graph_run` resolves both a bare filing id and the full ref;
`upsert_module` refuses acceptance_criteria outside 20-2000 characters;
`link_work_items` refuses an unknown relation_type; `call_tool` wraps every
`ToolError` and unknown tool name into `{"error": {...}}`.
"""
from __future__ import annotations

import pytest

from hyperspace.store import Store
from hyperspace.tools import TOOLS, ToolError, call_tool
from hyperspace.tools.reads import (
    append_worklog,
    assign_cycle_work_items,
    get_project,
    get_recent_activity,
    link_initiative_objects,
    list_initiative_links,
    list_initiatives,
    list_agents,
    list_projects,
    unassign_cycle_work_items,
    upsert_cycle,
    upsert_initiative,
    upsert_module,
    upsert_project,
)
from hyperspace.tools.work_items import (
    get_graph_run,
    get_work_item,
    link_work_items,
    list_work_items,
    upsert_work_item,
)

# Straight from the contract's own calibration set (candidate.py's
# `_PLACEHOLDER_PREFIXES` docstring, "MUST match (rejected)") — long enough to
# clear `Specification.problem`'s 40-character floor, and recognized by
# `is_placeholder` because it starts with "TODO".
PLACEHOLDER_PROBLEM = "TODO - to be determined once the scope of this work has been established."


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / ".hyperspace" / "graph.db"
    s = Store.init(db_path)
    s.upsert_project(code="demo-project", name="Demo")
    try:
        yield s
    finally:
        s.close()


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
            "problem": "The graph tools package has no function table yet, so nothing can file work.",
            "why_it_matters": "Without a function table the loop and console cannot file, link, list or log work.",
            "context_pointer": "brief.md step 2, hsp-graph-tools row.",
        },
        "source_references": [{"uri": "worklog entry deadbeef"}],
        "effort_level": "medium",
        "module": None,
        "acceptance_criteria": [
            {
                "statement": "The unit tests for the graph tools package pass.",
                "verification": {"kind": "command_check", "check_id": "tests"},
            }
        ],
        "proposer_identity": "engineer",
        "proposer_surface": "cli-mac",
        "uncertainty_notes": [],
    }
    payload.update(overrides)
    return payload


# ── upsert_work_item — the happy path ────────────────────────────────────


def test_upsert_work_item_files_row_and_filing(store):
    result = upsert_work_item(store, **_candidate())
    assert result["status"] == "filed"
    row = result["row"]
    assert row["external_id"] == "demo-project:wi-1"
    assert row["name"] == "Do the thing"
    expected_ref = f"graph://filing/{result['filing_id']}/item/demo-project:wi-1#acceptance_criteria"
    assert row["acceptance_criteria_ref"] == expected_ref

    filing = store.get_filing(result["filing_id"])
    assert filing["idempotency_key"] == "wi-1-create"


# ── upsert_work_item — refusals ──────────────────────────────────────────


def test_upsert_work_item_missing_criteria_refused(store):
    payload = _candidate()
    del payload["acceptance_criteria"]
    with pytest.raises(ToolError) as exc_info:
        upsert_work_item(store, **payload)
    assert exc_info.value.code == "validation"
    assert store.get_work_item(external_id="demo-project:wi-1", project_code="demo-project") is None


def test_upsert_work_item_placeholder_criteria_refused(store):
    payload = _candidate(
        specification={
            "problem": PLACEHOLDER_PROBLEM,
            "why_it_matters": "Without a function table the loop and console cannot file, link, list or log work.",
            "context_pointer": "brief.md step 2, hsp-graph-tools row.",
        }
    )
    with pytest.raises(ToolError) as exc_info:
        upsert_work_item(store, **payload)
    assert exc_info.value.code == "validation"
    assert store.get_work_item(external_id="demo-project:wi-1", project_code="demo-project") is None


# ── upsert_work_item — S2: criteria update mints a fresh filing key ──────


def test_upsert_work_item_update_criteria_mints_fresh_key(store):
    first = upsert_work_item(store, **_candidate())
    original_key = "wi-1-create"

    second = upsert_work_item(
        store,
        **_candidate(
            idempotency_key=original_key,
            update_acceptance_criteria=True,
            acceptance_criteria=[
                {
                    "statement": "The unit tests pass AND the smoke probe passes too.",
                    "verification": {"kind": "command_check", "check_id": "tests"},
                }
            ],
        ),
    )

    assert second["status"] == "updated"
    assert second["filing_id"] != first["filing_id"]

    new_filing = store.get_filing(second["filing_id"])
    assert new_filing["idempotency_key"] != original_key

    first_filing_still = store.get_filing(first["filing_id"])
    assert first_filing_still["idempotency_key"] == original_key
    assert first_filing_still["acceptance_criteria_json"][0]["statement"] == (
        "The unit tests for the graph tools package pass."
    )

    row = second["row"]
    expected_ref = f"graph://filing/{second['filing_id']}/item/demo-project:wi-1#acceptance_criteria"
    assert row["acceptance_criteria_ref"] == expected_ref

    resolved = store.resolve_criteria(row["acceptance_criteria_ref"])
    assert resolved[0]["statement"] == "The unit tests pass AND the smoke probe passes too."


def test_upsert_work_item_criteria_change_without_flag_refused(store):
    first = upsert_work_item(store, **_candidate())

    with pytest.raises(ToolError) as exc_info:
        upsert_work_item(
            store,
            **_candidate(
                idempotency_key="wi-1-create",
                acceptance_criteria=[
                    {
                        "statement": "A completely different criterion text.",
                        "verification": {"kind": "command_check", "check_id": "tests"},
                    }
                ],
            ),
        )
    assert exc_info.value.code == "conflict"
    # unchanged — the conflicting call wrote nothing
    assert store.latest_filing("demo-project:wi-1")["id"] == first["filing_id"]


def test_upsert_work_item_idempotent_repeat(store):
    first = upsert_work_item(store, **_candidate())
    second = upsert_work_item(store, **_candidate())
    assert second["status"] == "unchanged"
    assert second["filing_id"] == first["filing_id"]
    assert second["row"]["id"] == first["row"]["id"]


def test_upsert_work_item_done_sets_completed_by_console(store):
    result = upsert_work_item(
        store,
        **_candidate(
            idempotency_key="wi-1-done",
            state="done",
            acceptance_criteria=[
                {"statement": "Exits 0 when run against the fixture.", "verification": {"kind": "command_check", "check_id": "tests"}}
            ],
        ),
    )
    assert result["row"]["completed_by"] == "hyperspace-console"


# ── get_graph_run ─────────────────────────────────────────────────────────


def test_get_graph_run_resolves_ref_and_bare_id(store):
    filed = upsert_work_item(store, **_candidate())
    ref = filed["row"]["acceptance_criteria_ref"]

    via_ref = get_graph_run(store, ref)
    assert via_ref["filing_id"] == filed["filing_id"]
    assert via_ref["external_id"] == "demo-project:wi-1"
    assert via_ref["idempotency_key"] == "wi-1-create"
    assert isinstance(via_ref["acceptance_criteria"], list)

    via_bare_id = get_graph_run(store, filed["filing_id"])
    assert via_bare_id == via_ref


def test_get_graph_run_not_found(store):
    with pytest.raises(ToolError) as exc_info:
        get_graph_run(store, "graph://filing/does-not-exist/item/x#acceptance_criteria")
    assert exc_info.value.code == "not_found"


# ── get_work_item / list_work_items ──────────────────────────────────────


def test_get_work_item(store):
    upsert_work_item(store, **_candidate())
    row = get_work_item(store, external_id="demo-project:wi-1", project="demo-project")
    assert row["name"] == "Do the thing"
    assert get_work_item(store, id=row["id"])["external_id"] == "demo-project:wi-1"


def test_get_work_item_requires_a_key(store):
    with pytest.raises(ToolError) as exc_info:
        get_work_item(store)
    assert exc_info.value.code == "validation"


def test_list_work_items(store):
    upsert_work_item(store, **_candidate())
    upsert_work_item(
        store,
        **_candidate(external_id="demo-project:wi-2", idempotency_key="wi-2-create", state="ready"),
    )

    all_items = list_work_items(store, project="demo-project")
    assert {r["external_id"] for r in all_items} == {"demo-project:wi-1", "demo-project:wi-2"}

    ready_only = list_work_items(store, project="demo-project", state="ready")
    assert {r["external_id"] for r in ready_only} == {"demo-project:wi-2"}

    task_only = list_work_items(store, project="demo-project", type="task")
    assert len(task_only) == 2

    root_only = list_work_items(store, project="demo-project", parent=None)
    assert len(root_only) == 2  # neither item has a parent

    unfiltered_by_parent = list_work_items(store, project="demo-project")
    assert len(unfiltered_by_parent) == 2


# ── link_work_items ───────────────────────────────────────────────────────


def test_link_work_items(store):
    upsert_work_item(store, **_candidate())
    upsert_work_item(store, **_candidate(external_id="demo-project:wi-2", idempotency_key="wi-2-create"))
    rel = link_work_items(
        store, project="demo-project", item="demo-project:wi-1",
        related_item="demo-project:wi-2", relation_type="blocks",
    )
    assert rel["relation_type"] == "blocks"


def test_link_work_items_unknown_relation_type_refused(store):
    upsert_work_item(store, **_candidate())
    upsert_work_item(store, **_candidate(external_id="demo-project:wi-2", idempotency_key="wi-2-create"))
    with pytest.raises(ToolError) as exc_info:
        link_work_items(
            store, project="demo-project", item="demo-project:wi-1",
            related_item="demo-project:wi-2", relation_type="nonsense",
        )
    assert exc_info.value.code == "validation"


def test_link_work_items_unknown_item_not_found(store):
    upsert_work_item(store, **_candidate())
    with pytest.raises(ToolError) as exc_info:
        link_work_items(
            store, project="demo-project", item="demo-project:wi-1",
            related_item="demo-project:nonexistent", relation_type="blocks",
        )
    assert exc_info.value.code == "not_found"


# ── upsert_module ─────────────────────────────────────────────────────────


def test_upsert_module_typed_result(store):
    result = upsert_module(
        store, project="demo-project", external_id="demo-project:mod-1",
        name="Module One", description="A module.", state="ready",
        team=["engineer"], folder_path="/workspace/demo-project/mod-1",
        acceptance_criteria="Every child work item in this module is done.",
    )
    assert result["external_id"] == "demo-project:mod-1"
    assert result["name"] == "Module One"
    assert result["acceptance_criteria"].startswith("Every child")


def test_upsert_module_short_criteria_refused(store):
    with pytest.raises(ToolError) as exc_info:
        upsert_module(
            store, project="demo-project", external_id="demo-project:mod-2",
            acceptance_criteria="short",
        )
    assert exc_info.value.code == "validation"


# ── append_worklog ────────────────────────────────────────────────────────


def test_append_worklog(store):
    row = append_worklog(store, author="engineer", project="demo-project", summary="Did a thing.")
    assert row["author"] == "engineer"
    assert row["summary"] == "Did a thing."


def test_append_worklog_refuses_long_summary(store):
    with pytest.raises(ToolError) as exc_info:
        append_worklog(store, author="engineer", project="demo-project", summary="x" * 281)
    assert exc_info.value.code == "validation"


def test_get_recent_activity(store):
    append_worklog(store, author="engineer", project="demo-project", summary="One.")
    append_worklog(store, author="engineer", project="demo-project", summary="Two.")
    recent = get_recent_activity(store, limit=1)
    assert len(recent) == 1
    assert recent[0]["summary"] == "Two."


# ── projects ──────────────────────────────────────────────────────────────


def test_get_project(store):
    row = get_project(store, code="demo-project")
    assert row["code"] == "demo-project"


def test_list_projects(store):
    upsert_project(store, code="other-project", name="Other", status="archived")
    all_projects = list_projects(store)
    assert {r["code"] for r in all_projects} == {"demo-project", "other-project"}

    archived_only = list_projects(store, status="archived")
    assert {r["code"] for r in archived_only} == {"other-project"}


def test_upsert_project(store):
    row = upsert_project(store, code="new-project", name="New Project", status="planned")
    assert row["code"] == "new-project"
    assert row["name"] == "New Project"


# ── cycles ────────────────────────────────────────────────────────────────


def test_upsert_cycle_and_assignment(store):
    upsert_work_item(store, **_candidate())
    cycle = upsert_cycle(
        store, project="demo-project", external_id="demo-project:cycle-1", name="Cycle One",
    )
    assert cycle["external_id"] == "demo-project:cycle-1"

    result = assign_cycle_work_items(
        store, project="demo-project", cycle="demo-project:cycle-1",
        work_items=["demo-project:wi-1"],
    )
    assert result["work_items"] == ["demo-project:wi-1"]

    unassigned = unassign_cycle_work_items(
        store, project="demo-project", cycle="demo-project:cycle-1",
        work_items=["demo-project:wi-1"],
    )
    assert unassigned["work_items"] == ["demo-project:wi-1"]


def test_assign_cycle_work_items_unknown_cycle_not_found(store):
    with pytest.raises(ToolError) as exc_info:
        assign_cycle_work_items(
            store, project="demo-project", cycle="demo-project:nonexistent", work_items=[],
        )
    assert exc_info.value.code == "not_found"


# ── initiatives ───────────────────────────────────────────────────────────


def test_upsert_initiative_and_links(store):
    upsert_work_item(store, **_candidate())
    init = upsert_initiative(store, external_id="init-1", title="Initiative One")
    assert init["external_id"] == "init-1"

    result = link_initiative_objects(
        store, initiative="init-1", projects=["demo-project"], work_items=["demo-project:wi-1"],
    )
    assert result["status"] == "linked"
    link_types = {link["link_type"] for link in result["links"]}
    assert link_types == {"project", "work_item"}

    links = list_initiative_links(store, initiative="init-1")
    assert {link["link_type"] for link in links} == {"project", "work_item"}


def test_link_initiative_objects_unknown_initiative_not_found(store):
    with pytest.raises(ToolError) as exc_info:
        link_initiative_objects(store, initiative="does-not-exist", projects=["demo-project"])
    assert exc_info.value.code == "not_found"


def test_list_initiatives(store):
    upsert_initiative(store, external_id="init-1", title="Initiative One", state="in-progress")
    upsert_initiative(store, external_id="init-2", title="Initiative Two", state="planned")

    all_initiatives = list_initiatives(store)
    assert {r["external_id"] for r in all_initiatives} == {"init-1", "init-2"}

    in_progress_only = list_initiatives(store, state="in-progress")
    assert {r["external_id"] for r in in_progress_only} == {"init-1"}


# ── list_agents ───────────────────────────────────────────────────────────


def test_list_agents_default_none(store):
    agents = list_agents(store)
    assert agents == [{
        "agent_name": "none", "harness": "hyperspace", "substrate": "local",
        "team": "", "tier": "execution", "proposed_lifecycle": "Stable", "can_spawn": False,
    }]


def test_list_agents_reads_config(tmp_path):
    db_path = tmp_path / ".hyperspace" / "graph.db"
    s = Store.init(db_path)  # creates .hyperspace/ first
    config_path = tmp_path / ".hyperspace" / "config.toml"
    config_path.write_text('judge = "anthropic"\n')
    try:
        agents = list_agents(s)
        assert agents[0]["agent_name"] == "anthropic"
    finally:
        s.close()


# ── registry / call_tool ─────────────────────────────────────────────────

SIXTEEN_TOOL_NAMES = {
    "upsert_work_item", "get_graph_run", "list_work_items", "append_worklog",
    "link_work_items", "upsert_module", "get_recent_activity",
    "list_initiative_links", "list_agents", "get_work_item", "get_project",
    "list_projects", "upsert_cycle", "assign_cycle_work_items",
    "upsert_initiative", "link_initiative_objects",
}
SEVENTEENTH_TOOL_NAME = "list_initiatives"


def test_tools_table_contains_the_seventeen():
    assert (SIXTEEN_TOOL_NAMES | {SEVENTEENTH_TOOL_NAME}) <= TOOLS.keys()


def test_tools_table_also_contains_upsert_project_not_in_the_sixteen():
    assert "upsert_project" in TOOLS
    assert "upsert_project" not in SIXTEEN_TOOL_NAMES


def test_every_tool_input_schema_is_a_valid_json_schema_object():
    for name, spec in TOOLS.items():
        assert spec.input_schema.get("type") == "object", name
        assert "properties" in spec.input_schema, name
        assert "required" in spec.input_schema, name


def test_call_tool_dispatches(store):
    result = call_tool(store, "get_project", {"code": "demo-project"})
    assert result["code"] == "demo-project"


def test_call_tool_wraps_tool_error(store):
    result = call_tool(
        store, "upsert_module",
        {"project": "demo-project", "external_id": "demo-project:mod-x", "acceptance_criteria": "short"},
    )
    assert result == {"error": {"code": "validation", "message": result["error"]["message"]}}


def test_call_tool_unknown_tool_name(store):
    result = call_tool(store, "no_such_tool", {})
    assert result["error"]["code"] == "not_found"
