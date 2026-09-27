"""hyperspace/tools/reads.py — the reads, and the writes that are not work
items, over the store (row T2.2)."""
from __future__ import annotations

from ._config import read_judge
from ..store import Store
from .registry import ToolError

_MODULE_CRITERIA_MIN = 20
_MODULE_CRITERIA_MAX = 2000
_WORKLOG_SUMMARY_MAX = 280


# ── modules ──────────────────────────────────────────────────────────────

def upsert_module(
    store: Store, *, project: str, external_id: str, idempotency_key: str | None = None,
    name: str | None = None, description: str | None = None, state: str | None = None,
    team: list[str] | None = None, folder_path: str | None = None,
    acceptance_criteria: str | None = None, acceptance_criteria_ref: str | None = None,
    parent_module: str | None = None,
) -> dict:
    """Mirrors the module contract's 20-2000 character rule on
    `acceptance_criteria` — the vendored `CandidateWorkItem` contract has no
    module counterpart, so this length check is this tool's own, applied the
    same way."""
    if acceptance_criteria is not None and not (
        _MODULE_CRITERIA_MIN <= len(acceptance_criteria) <= _MODULE_CRITERIA_MAX
    ):
        raise ToolError(
            "validation",
            f"acceptance_criteria must be {_MODULE_CRITERIA_MIN}-{_MODULE_CRITERIA_MAX} "
            f"characters (got {len(acceptance_criteria)})",
        )

    parent_module_id = None
    if parent_module is not None:
        parent = store.get_module(project_code=project, external_id=parent_module)
        parent_module_id = parent["id"] if parent else None

    fields = {
        k: v for k, v in {
            "name": name, "description": description, "state": state, "team": team,
            "folder_path": folder_path, "acceptance_criteria": acceptance_criteria,
            "acceptance_criteria_ref": acceptance_criteria_ref,
        }.items() if v is not None
    }
    if parent_module is not None:
        fields["parent_module_id"] = parent_module_id

    return store.upsert_module(project_code=project, external_id=external_id, **fields)


# ── projects ─────────────────────────────────────────────────────────────

def get_project(store: Store, *, code: str) -> dict | None:
    return store.get_project(code)


def list_projects(store: Store, *, status: str | list[str] | None = None) -> list[dict]:
    rows = store.list_projects()
    if status is not None:
        wanted = {status} if isinstance(status, str) else set(status)
        rows = [r for r in rows if r.get("status") in wanted]
    return rows


def upsert_project(
    store: Store, *, code: str, name: str | None = None, description: str | None = None,
    status: str | None = None, parent_code: str | None = None, owner: str | None = None,
    client: str | None = None, next_action: str | None = None, folder_path: str | None = None,
    team: list[str] | None = None,
) -> dict:
    fields = {
        k: v for k, v in {
            "name": name, "description": description, "status": status,
            "parent_code": parent_code, "owner": owner, "client": client,
            "next_action": next_action, "folder_path": folder_path, "team": team,
        }.items() if v is not None
    }
    return store.upsert_project(code, **fields)


# ── worklog ──────────────────────────────────────────────────────────────

def append_worklog(
    store: Store, *, author: str, project: str, summary: str, detailed: str | None = None,
    tags: list[str] | None = None, client: str | None = None, surface: str | None = None,
    work_item_id: str | None = None,
) -> dict:
    if len(summary) > _WORKLOG_SUMMARY_MAX:
        raise ToolError(
            "validation", f"summary exceeds {_WORKLOG_SUMMARY_MAX} characters (got {len(summary)})"
        )
    return store.append_worklog(
        author=author, summary=summary, project=project, detailed=detailed,
        tags=tags, client=client, surface=surface, work_item_id=work_item_id,
    )


def get_recent_activity(store: Store, *, limit: int = 10) -> list[dict]:
    return store.recent_worklog(limit=limit)


def search_worklog(
    store: Store, *, project: str | None = None, author: str | None = None,
    tags: list[str] | None = None, from_date: str | None = None, to_date: str | None = None,
) -> list[dict]:
    return store.search_worklog(
        project=project, author=author, tags=tags, from_date=from_date, to_date=to_date,
    )


# ── cycles ───────────────────────────────────────────────────────────────

def upsert_cycle(
    store: Store, *, project: str, external_id: str, idempotency_key: str | None = None,
    name: str | None = None, description: str | None = None, state: str | None = None,
    start_date: str | None = None, end_date: str | None = None,
) -> dict:
    fields = {
        k: v for k, v in {
            "name": name, "description": description, "state": state,
            "start_date": start_date, "end_date": end_date,
        }.items() if v is not None
    }
    return store.upsert_cycle(project_code=project, external_id=external_id, **fields)


def _require_cycle(store: Store, project: str, cycle: str) -> dict:
    # `Store` has no PUBLIC `get_cycle` (only the private `_get_cycle_row` its
    # own `upsert_cycle` uses internally) — see the report's concerns section.
    cycle_row = store._get_cycle_row(project, cycle)  # noqa: SLF001
    if cycle_row is None:
        raise ToolError("not_found", f"cycle not found: {cycle!r}")
    return cycle_row


def assign_cycle_work_items(
    store: Store, *, project: str, cycle: str, work_items: list[str],
    idempotency_key: str | None = None,
) -> dict:
    cycle_row = _require_cycle(store, project, cycle)
    assigned: list[str] = []
    for ext_id in work_items:
        wi = store.get_work_item(project_code=project, external_id=ext_id)
        if wi is None:
            raise ToolError("not_found", f"work item not found: {ext_id!r}")
        store.assign_cycle(cycle_row["id"], wi["id"])
        assigned.append(ext_id)
    return {"status": "assigned", "cycle": cycle, "work_items": assigned}


def unassign_cycle_work_items(
    store: Store, *, project: str, cycle: str, work_items: list[str],
    idempotency_key: str | None = None,
) -> dict:
    cycle_row = _require_cycle(store, project, cycle)
    unassigned: list[str] = []
    for ext_id in work_items:
        wi = store.get_work_item(project_code=project, external_id=ext_id)
        if wi is None:
            raise ToolError("not_found", f"work item not found: {ext_id!r}")
        store.unassign_cycle(cycle_row["id"], wi["id"])
        unassigned.append(ext_id)
    return {"status": "unassigned", "cycle": cycle, "work_items": unassigned}


# ── initiatives ──────────────────────────────────────────────────────────

def upsert_initiative(
    store: Store, *, external_id: str, title: str, idempotency_key: str | None = None,
    description: str | None = None, state: str | None = None, doc_paths: list[str] | None = None,
) -> dict:
    fields = {
        k: v for k, v in {
            "title": title, "description": description, "state": state, "doc_paths": doc_paths,
        }.items() if v is not None
    }
    return store.upsert_initiative(external_id, **fields)


def _require_initiative(store: Store, initiative: str) -> dict:
    init_row = store.get_initiative(external_id=initiative)
    if init_row is None:
        raise ToolError("not_found", f"initiative not found: {initiative!r}")
    return init_row


def link_initiative_objects(
    store: Store, *, initiative: str, idempotency_key: str | None = None,
    projects: list[str] | None = None, modules: list[str] | None = None,
    work_items: list[str] | None = None,
) -> dict:
    init_row = _require_initiative(store, initiative)
    for code in projects or []:
        store.link_initiative(init_row["id"], "project", code)
    for ext_id in modules or []:
        store.link_initiative(init_row["id"], "module", ext_id)
    for ext_id in work_items or []:
        store.link_initiative(init_row["id"], "work_item", ext_id)
    return {"status": "linked", "links": store.list_initiative_links(init_row["id"])}


def list_initiative_links(store: Store, *, initiative: str) -> list[dict]:
    init_row = _require_initiative(store, initiative)
    return store.list_initiative_links(init_row["id"])


def list_initiatives(store: Store, *, state: str | list[str] | None = None) -> list[dict]:
    rows = store.list_initiatives()
    if state is not None:
        wanted = {state} if isinstance(state, str) else set(state)
        rows = [r for r in rows if r.get("state") in wanted]
    return rows


# ── agents (local stub) ──────────────────────────────────────────────────

def list_agents(store: Store) -> list[dict]:
    """Local stub: returns the configured judge — read from
    `.hyperspace/config.toml` beside the open database file, if present — as
    the only agent."""
    config_path = store.path.parent / "config.toml"
    judge = read_judge(config_path)
    return [{
        "agent_name": judge,
        "harness": "hyperspace",
        "substrate": "local",
        "team": "",
        "tier": "execution",
        "proposed_lifecycle": "Stable",
        "can_spawn": False,
    }]
