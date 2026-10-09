"""hyperspace/tools/work_items.py — the row-writing half of the graph tools (row T2.2).

`upsert_work_item` is both proposer-validator and committer in this local,
queue-free build (decided in the brief): it builds a `CandidateWorkItem`,
refuses on contract failure (missing/placeholder criteria, extra fields,
malformed verification predicates — whatever the vendored contract refuses),
then writes the work-item row and its immutable filing directly through
`Store`. S2 (a criteria update mints a fresh filing under a fresh key) is
enforced here, not in `Store` — `Store.add_filing` will happily write any
filing it's given; the decision about WHEN a fresh key is required is this
module's job.

Three doors write `state="done"`, and which one a write came through is decided
by the CODE PATH, never by a field the caller sends (ported from the ops
server's 0.9.15 / 0.9.17 done door):

  agent (MCP, stdio)   `upsert_work_item`          refused — no label, no write
  verifier             `verify/deps.py` commit      `hyperspace-verifier`
  console (HTTP)       `console_upsert_work_item`   `hyperspace-console`
                       `console_patch_work_item`    `hyperspace-console`

`console_upsert_work_item` takes two shapes. A proposal (`CandidateWorkItem`) is
filed exactly as the agent door files it. The console's own create form sends a
flat row (a name, a description, one block of criteria text) — the trusted
console is not subject to the agent-only proposal requirements (see
`contracts/candidate.py`), so that row is written directly, with no filing: there
are no typed criteria for the verifier to judge, and a person closes the row.

The agent door is the default everywhere. Only `call_tool(..., console=True)`,
which only `http/routes.py::_call_as_console` passes, reaches the console door; and
`console_patch_work_item` is called only by `http/routes.py::route_patch`.
"""
from __future__ import annotations

import uuid
from typing import Any, get_args

from pydantic import ValidationError

from ..contracts.candidate import AcceptanceCriterion, CandidateWorkItem, SourceReference, Specification
from ..contracts.enums import WorkItemType, is_done_flip
from ..store import Store
from ..store.store import WORK_ITEM_STATES
from .registry import ToolError

_UNSET = object()

#: `completed_by` for a row a person closed through the console's HTTP door.
#: Mirrored in `bin/node_gates.py` (`_CONSOLE_LABEL`), which accepts it.
CONSOLE_IDENTITY = "hyperspace-console"

#: What an agent is told when it sends `state="done"` through the MCP tool.
AGENT_DONE_REFUSAL = (
    'state="done" is not accepted through upsert_work_item. Close the row with '
    "complete_workitem on this same hyperspace server (it verifies the change on "
    "disk and flips the row in the same call), or ask the user to close the task "
    "in the console. Nothing was written."
)


def _strip_underscore_keys(value: Any) -> Any:
    """Strips `_`-prefixed keys at every depth. The contract forbids extra
    fields (`extra: "forbid"`) — a caller's own bookkeeping annotation
    (e.g. `_note`) must not reach `CandidateWorkItem` and blow up validation
    for a reason that has nothing to do with the proposal itself."""
    if isinstance(value, dict):
        return {k: _strip_underscore_keys(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_strip_underscore_keys(v) for v in value]
    return value


def _trim(text: str, limit: int = 1200) -> str:
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


#: The length rule for acceptance criteria written as one block of text (a module's,
#: and a task created from the console). The agent's work items carry typed criteria
#: instead, which the contract bounds on its own.
CRITERIA_TEXT_MIN = 20
CRITERIA_TEXT_MAX = 2000


def check_criteria_text(text: str | None) -> None:
    if text is not None and not (CRITERIA_TEXT_MIN <= len(text) <= CRITERIA_TEXT_MAX):
        raise ToolError(
            "validation",
            f"acceptance_criteria must be {CRITERIA_TEXT_MIN}-{CRITERIA_TEXT_MAX} "
            f"characters (got {len(text)})",
        )


def _source_references(refs: Any) -> list[dict]:
    try:
        if not isinstance(refs, list):
            raise TypeError("source_references must be a list")
        return [SourceReference(**r).model_dump(mode="json") for r in refs]
    except (TypeError, ValidationError) as exc:
        raise ToolError("validation", _trim(f"source_references: {exc}")) from exc


def _new_filing_key() -> str:
    return f"criteria-update-{uuid.uuid4()}"


def _resolve_module_id(store: Store, project: str, module_external_id: str | None) -> str | None:
    """Resolves a `module` external_id to its store id, or refuses.

    Controller ruling (2026-09-27): gear4's emit demi files modules before
    items, so an unresolved `module` is a typo, not a legitimate ordering
    gap — refuse loudly rather than silently writing `module_id = None`.
    """
    if module_external_id is None:
        return None
    mod = store.get_module(project_code=project, external_id=module_external_id)
    if mod is None:
        raise ToolError(
            "not_found",
            f"module not found: {module_external_id!r} (project {project!r})",
        )
    return mod["id"]


def _resolve_parent_id(store: Store, project: str, parent_external_id: str | None) -> str | None:
    """Resolves a `parent_work_item` external_id to its store id, or refuses
    (same ruling as `_resolve_module_id` — an unresolved parent is a typo)."""
    if parent_external_id is None:
        return None
    parent = store.get_work_item(project_code=project, external_id=parent_external_id)
    if parent is None:
        raise ToolError(
            "not_found",
            f"parent work item not found: {parent_external_id!r} (project {project!r})",
        )
    return parent["id"]


def _render_description(spec: Specification) -> str:
    return (
        f"Problem: {spec.problem}\n\n"
        f"Why it matters: {spec.why_it_matters}\n\n"
        f"Context: {spec.context_pointer}"
    )


def _render_criteria_text(criteria: list[AcceptanceCriterion]) -> str:
    return "\n".join(f"- {c.statement}" for c in criteria)


def _row_fields_from_candidate(
    store: Store, candidate: CandidateWorkItem, closure_label: str | None
) -> dict:
    fields: dict[str, Any] = {
        "name": candidate.name,
        "type": candidate.type,
        "state": candidate.state,
        "module_id": _resolve_module_id(store, candidate.project, candidate.module),
        "parent_work_item_id": _resolve_parent_id(store, candidate.project, candidate.parent_work_item),
        "assignee_agent": candidate.assignee_agent,
        "effort_level": candidate.effort_level,
        "description": _render_description(candidate.specification),
        "source_references": [sr.model_dump(mode="json") for sr in candidate.source_references],
        "added_by": candidate.proposer_identity,
        "idempotency_key": candidate.idempotency_key,
        "team": candidate.team or [],
        "acceptance_criteria": _render_criteria_text(candidate.acceptance_criteria),
        "uncertainty_notes": [u.model_dump(mode="json") for u in candidate.uncertainty_notes],
    }
    # `closure_label` is the door's own label, handed in by the caller of this
    # module — never read from the candidate (the contract forbids extra
    # fields, so a caller cannot send one). The verifier stamps its own label
    # through `Store.set_work_item_state`, not through here.
    if closure_label is not None and is_done_flip(candidate):
        fields["completed_by"] = closure_label
    return fields


def upsert_work_item(store: Store, **candidate_fields: Any) -> dict:
    """The agent door (MCP): contract-validated filing that REFUSES `state="done"`
    on CREATE and UPDATE alike, before any write. An agent closes a row through
    `complete_workitem`, or hands the closure to the user. See `_file_work_item`
    for the filing semantics."""
    return _file_work_item(store, candidate_fields, closure_label=None)


#: Keys only a proposal carries (each is a required key of `CandidateWorkItem`). Any
#: one of them present means the caller sent a proposal, whatever else is missing.
_PROPOSAL_KEYS = frozenset(
    {"specification", "proposer_identity", "proposer_surface", "effort_level", "uncertainty_notes"}
)


def console_upsert_work_item(store: Store, **fields: Any) -> dict:
    """The console door (HTTP): a proposal is filed as the agent door files it,
    except that a person's `state="done"` is accepted and stamped
    `hyperspace-console`; the console's flat create row goes to
    `_file_console_row`. Reached only through `call_tool(..., console=True)`."""
    if _PROPOSAL_KEYS & fields.keys():
        return _file_work_item(store, fields, closure_label=CONSOLE_IDENTITY)
    return _file_console_row(store, fields)


def _file_work_item(store: Store, candidate_fields: dict[str, Any], *, closure_label: str | None) -> dict:
    """Contract-validated filing, shared by both doors. `closure_label` is the
    door's stamp for a `state="done"` write; `None` (the agent door) refuses a
    done claim instead. Returns
    `{"status": "filed"|"updated"|"unchanged", "row": <work item dict>, "filing_id": ...}`.

    CREATE (no existing row/filing): writes the row, then a filing under the
    candidate's own `idempotency_key`.

    UPDATE with unchanged criteria: writes the row; no new filing.

    UPDATE with changed criteria and `update_acceptance_criteria=False`:
    refused (`ToolError("conflict", ...)`) — criteria are immutable unless the
    caller opts in. Nothing is written.

    UPDATE with changed criteria and `update_acceptance_criteria=True`: writes
    the row, then a NEW filing under a freshly minted key (S2) — the filings
    table's `idempotency_key` column is UNIQUE, so a fresh filing can never
    reuse the original key.
    """
    cleaned = _strip_underscore_keys(candidate_fields)
    try:
        candidate = CandidateWorkItem(**cleaned)
    except ValidationError as exc:
        raise ToolError("validation", _trim(str(exc))) from exc

    # A completion claim is a property of the CANDIDATE, so it is refused here,
    # ahead of every lookup and write, whether or not the row exists.
    if closure_label is None and is_done_flip(candidate):
        raise ToolError("refused", AGENT_DONE_REFUSAL)

    project = candidate.project
    external_id = candidate.external_id

    existing = store.get_work_item(external_id=external_id, project_code=project)
    latest = store.latest_filing(external_id)

    candidate_dict = candidate.model_dump(mode="json")
    new_criteria = candidate_dict["acceptance_criteria"]
    stored_criteria = (latest or {}).get("acceptance_criteria_json")
    criteria_changed = latest is not None and stored_criteria != new_criteria

    if criteria_changed and not candidate.update_acceptance_criteria:
        raise ToolError(
            "conflict",
            f"acceptance_criteria for {external_id!r} differ from the last filed "
            f"criteria and update_acceptance_criteria was not set — criteria are "
            f"immutable unless the caller opts in.",
        )

    row_fields = _row_fields_from_candidate(store, candidate, closure_label)
    row = store.upsert_work_item(project_code=project, external_id=external_id, **row_fields)

    if latest is None:
        # First-ever filing for this external_id — whether the row itself was
        # brand new, or already existed with no filing attached yet.
        filing_id = store.add_filing(
            external_id=external_id, project_code=project,
            idempotency_key=candidate.idempotency_key, candidate=candidate_dict,
        )
        status = "filed" if existing is None else "updated"
    elif criteria_changed:
        fresh_key = _new_filing_key()
        filing_id = store.add_filing(
            external_id=external_id, project_code=project,
            idempotency_key=fresh_key, candidate=candidate_dict,
        )
        status = "updated"
    elif latest["idempotency_key"] == candidate.idempotency_key:
        # Same key, same (unchanged) criteria — idempotent repeat.
        filing_id = latest["id"]
        status = "unchanged"
    else:
        # Criteria unchanged, but a fresh idempotency_key was sent (e.g. a
        # plain state flip) — no new filing needed.
        filing_id = latest["id"]
        status = "updated"

    row = store.get_work_item(id=row["id"])
    return {"status": status, "row": row, "filing_id": filing_id}


#: The keys of the console's create body (Caelos `src/app/App.tsx`, `api()`'s
#: work-items POST builder) plus the `project` the door takes from the URL.
CONSOLE_ROW_FIELDS = frozenset({
    "project", "external_id", "name", "type", "state", "description", "acceptance_criteria",
    "acceptance_criteria_ref", "assignee_agent", "team", "idempotency_key", "module",
    "parent_work_item", "source_references",
})

_WORK_ITEM_TYPES = frozenset(get_args(WorkItemType))


def _file_console_row(store: Store, fields: dict[str, Any]) -> dict:
    """Writes the console's create form as a work item. Every value is validated
    before the first write, and a refusal says which field and why. A row that
    already has this `external_id` is updated: only the keys sent change. The
    flip into `done` is the one `console_patch_work_item` makes (stamped
    `hyperspace-console`, `completed_at` set, the closure logged).

    Returns `{"status": "filed"|"updated", "row": ...}`, the shape the console
    unwraps."""
    fields = _strip_underscore_keys(fields)
    unknown = set(fields) - CONSOLE_ROW_FIELDS
    if unknown:
        raise ToolError("validation", f"unknown fields: {', '.join(sorted(unknown))}")

    project, external_id, name = fields.get("project"), fields.get("external_id"), fields.get("name")
    if not isinstance(project, str) or not project:
        raise ToolError("validation", "project is required")
    if not isinstance(external_id, str) or not external_id.strip() or len(external_id) > 255:
        raise ToolError("validation", "external_id must be a non-empty string of at most 255 characters")
    if not isinstance(name, str) or not name.strip() or len(name) > 500:
        raise ToolError("validation", "name must be a non-empty string of at most 500 characters")

    existing = store.get_work_item(external_id=external_id, project_code=project)
    current = existing or {}
    row_type = fields.get("type") or current.get("type") or "task"
    if row_type not in _WORK_ITEM_TYPES:
        raise ToolError("validation", f"invalid type: {row_type!r}")
    state = fields.get("state") or current.get("state") or "pending-review"
    if state not in WORK_ITEM_STATES:
        raise ToolError("validation", f"invalid state: {state!r}")
    text_keys = ("description", "acceptance_criteria", "acceptance_criteria_ref", "assignee_agent", "idempotency_key")
    for key in text_keys:
        if key in fields:
            _patch_text(fields, key)
    check_criteria_text(fields.get("acceptance_criteria"))
    team = fields.get("team")
    if team is not None and (not isinstance(team, list) or not all(isinstance(t, str) for t in team)):
        raise ToolError("validation", "team must be a list of strings")

    row_fields: dict[str, Any] = {"name": name, "type": row_type, "added_by": CONSOLE_IDENTITY}
    for key in text_keys:
        if key in fields:
            row_fields[key] = fields[key]
    if team is not None:
        row_fields["team"] = team
    if "source_references" in fields and fields["source_references"] is not None:
        row_fields["source_references"] = _source_references(fields["source_references"])
    if "module" in fields:
        row_fields["module_id"] = _resolve_module_id(store, project, fields["module"])
    if "parent_work_item" in fields:
        parent_id = _resolve_parent_id(store, project, fields["parent_work_item"])
        if parent_id is not None and parent_id == current.get("id"):
            raise ToolError("validation", "a work item cannot be its own parent")
        row_fields["parent_work_item_id"] = parent_id

    if existing is None:
        # Born in its state, so the row is never read with none; a row made `done` is
        # flipped below, which is what stamps and logs the closure.
        row_fields["state"] = "pending-review" if state == "done" else state

    row = store.upsert_work_item(project_code=project, external_id=external_id, **row_fields)
    if state != row.get("state"):
        store.set_work_item_state(
            row["id"], state, completed_by=CONSOLE_IDENTITY if state == "done" else None
        )
    return {
        "status": "filed" if existing is None else "updated",
        "row": store.get_work_item(id=row["id"]),
    }


#: The body keys the pinned console bundle (`ui/dist`, Caelos `dfcb46d`) sends on
#: `PATCH /api/work-items/<id>`. `tests/test_ui_bundle.py` reads the bundle and
#: fails if it ever sends a key outside this set.
PATCHABLE_FIELDS = frozenset({
    "name", "description", "acceptance_criteria", "acceptance_criteria_ref", "state",
    "assignee_agent", "team", "module", "project", "parent_work_item", "position",
    "source_references",
})


def _patch_text(body: dict, key: str) -> None:
    if body[key] is not None and not isinstance(body[key], str):
        raise ToolError("validation", f"{key} must be a string or null")


def console_patch_work_item(store: Store, row: dict, body: Any) -> dict:
    """The console door's partial update (`PATCH /api/work-items/<id>`): only the
    keys sent change; the rest keep their value. A change of `state` into `done`
    is stamped `hyperspace-console` and `completed_at`; a change out of `done`
    clears both; a PATCH that leaves `state` where it is never touches the stamp,
    so the door that closed a row is not rewritten by whoever edited it next.

    `row` is the existing row, resolved by the caller. The label is this
    function's, never a key of `body` (an unknown key is refused). Every value
    is validated before the first write. Returns `{"status": "updated", "row": ...}`,
    the shape the console unwraps.
    """
    if not isinstance(body, dict) or not body:
        raise ToolError("validation", "at least one mutable field is required")
    unknown = set(body) - PATCHABLE_FIELDS
    if unknown:
        raise ToolError("validation", f"unknown or immutable fields: {', '.join(sorted(unknown))}")

    project = row["project_code"]
    fields: dict[str, Any] = {}

    if "name" in body:
        name = body["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 500:
            raise ToolError("validation", "name must be a non-empty string of at most 500 characters")
        fields["name"] = name
    for key in ("description", "acceptance_criteria", "acceptance_criteria_ref", "assignee_agent"):
        if key in body:
            _patch_text(body, key)
            fields[key] = body[key]
    if (
        "acceptance_criteria" in body
        and body["acceptance_criteria"] is None
        and row.get("acceptance_criteria") is not None
    ):
        raise ToolError("validation", "acceptance_criteria cannot be cleared once set")
    if "team" in body:
        team = body["team"]
        if not isinstance(team, list) or not all(isinstance(t, str) for t in team):
            raise ToolError("validation", "team must be a list of strings")
        fields["team"] = team
    if "position" in body:
        position = body["position"]
        if position is not None and (isinstance(position, bool) or not isinstance(position, (int, float))):
            raise ToolError("validation", "position must be a number or null")
        fields["position"] = position
    if "source_references" in body:
        fields["source_references"] = _source_references(body["source_references"])
    if "module" in body:
        fields["module_id"] = _resolve_module_id(store, project, body["module"])
    if "parent_work_item" in body:
        parent_id = _resolve_parent_id(store, project, body["parent_work_item"])
        if parent_id is not None and parent_id == row["id"]:
            raise ToolError("validation", "a work item cannot be its own parent")
        fields["parent_work_item_id"] = parent_id
    if "project" in body and body["project"] != project:
        raise ToolError("validation", "moving a work item to another project is not supported")
    new_state = body.get("state", row.get("state"))
    if "state" in body and new_state not in WORK_ITEM_STATES:
        raise ToolError("validation", f"invalid state: {new_state!r}")

    if fields:
        store.upsert_work_item(project_code=project, external_id=row["external_id"], **fields)
    if new_state != row.get("state"):
        store.set_work_item_state(
            row["id"], new_state, completed_by=CONSOLE_IDENTITY if new_state == "done" else None
        )
    return {"status": "updated", "row": store.get_work_item(id=row["id"])}


def get_work_item(
    store: Store, *, external_id: str | None = None, id: str | None = None, project: str | None = None
) -> dict | None:
    if id is None and external_id is None:
        raise ToolError("validation", "get_work_item requires id or external_id")
    return store.get_work_item(id=id, external_id=external_id, project_code=project)


def list_work_items(
    store: Store,
    *,
    project: str | None = None,
    state: str | list[str] | None = None,
    type: str | list[str] | None = None,
    module: str | None = None,
    parent: str | None = _UNSET,
) -> list[dict]:
    """Mirrors the ops server's filter semantics: `state`/`type` accept a
    single value or a list; `module`/`parent` are external_ids resolved to
    the store's internal ids; `parent` is three-state — omitted (default,
    no filter), explicit `None` (root items only), or an external_id (direct
    children of that item)."""
    rows = store.list_work_items(project_code=project)

    if state is not None:
        wanted = {state} if isinstance(state, str) else set(state)
        rows = [r for r in rows if r.get("state") in wanted]

    if type is not None:
        wanted_types = {type} if isinstance(type, str) else set(type)
        rows = [r for r in rows if r.get("type") in wanted_types]

    if module is not None:
        mod = store.get_module(project_code=project, external_id=module)
        module_id = mod["id"] if mod else None
        rows = [r for r in rows if r.get("module_id") == module_id]

    if parent is _UNSET:
        pass
    elif parent is None:
        rows = [r for r in rows if r.get("parent_work_item_id") is None]
    else:
        parent_row = store.get_work_item(project_code=project, external_id=parent)
        parent_id = parent_row["id"] if parent_row else None
        rows = [r for r in rows if r.get("parent_work_item_id") == parent_id]

    return rows


def link_work_items(
    store: Store, *, project: str, item: str, related_item: str, relation_type: str,
    idempotency_key: str | None = None,
) -> dict:
    src = store.get_work_item(project_code=project, external_id=item)
    if src is None:
        raise ToolError("not_found", f"work item not found: {item!r}")
    dst = store.get_work_item(project_code=project, external_id=related_item)
    if dst is None:
        raise ToolError("not_found", f"work item not found: {related_item!r}")
    try:
        return store.add_relation(
            project_code=project, work_item_id=src["id"], related_work_item_id=dst["id"],
            relation_type=relation_type, idempotency_key=idempotency_key,
        )
    except ValueError as exc:
        raise ToolError("validation", str(exc)) from exc


def get_graph_run(store: Store, run_id: str) -> dict:
    """Resolves a filing reference — either the bare filing id, or the full
    `graph://filing/<id>/item/<external_id>#acceptance_criteria` ref — to the
    filing's recorded shape."""
    prefix = "graph://filing/"
    if run_id.startswith(prefix):
        rest = run_id[len(prefix):]
        filing_id, _, _tail = rest.partition("/item/")
        if not filing_id:
            raise ToolError("validation", f"malformed filing ref: {run_id!r}")
    else:
        filing_id = run_id

    filing = store.get_filing(filing_id)
    if filing is None:
        raise ToolError("not_found", f"no such filing: {filing_id!r}")

    return {
        "filing_id": filing["id"],
        "external_id": filing["external_id"],
        "acceptance_criteria": filing["acceptance_criteria_json"] or [],
        "filed_at": filing["filed_at"],
        "idempotency_key": filing["idempotency_key"],
    }
