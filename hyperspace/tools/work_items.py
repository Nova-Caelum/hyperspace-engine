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
"""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError

from ..contracts.candidate import AcceptanceCriterion, CandidateWorkItem, Specification
from ..store import Store
from .registry import ToolError

_UNSET = object()


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


def _new_filing_key() -> str:
    return f"criteria-update-{uuid.uuid4()}"


def _resolve_module_id(store: Store, project: str, module_external_id: str | None) -> str | None:
    if module_external_id is None:
        return None
    mod = store.get_module(project_code=project, external_id=module_external_id)
    return mod["id"] if mod else None


def _resolve_parent_id(store: Store, project: str, parent_external_id: str | None) -> str | None:
    if parent_external_id is None:
        return None
    parent = store.get_work_item(project_code=project, external_id=parent_external_id)
    return parent["id"] if parent else None


def _render_description(spec: Specification) -> str:
    return (
        f"Problem: {spec.problem}\n\n"
        f"Why it matters: {spec.why_it_matters}\n\n"
        f"Context: {spec.context_pointer}"
    )


def _render_criteria_text(criteria: list[AcceptanceCriterion]) -> str:
    return "\n".join(f"- {c.statement}" for c in criteria)


def _row_fields_from_candidate(store: Store, candidate: CandidateWorkItem) -> dict:
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
    # The console's override path (state="done" sent directly, bypassing the
    # verifier). The verifier always writes "hyperspace-verifier" itself —
    # this tool never sets completed_by for anything but this one path.
    if candidate.state == "done":
        fields["completed_by"] = "hyperspace-console"
    return fields


def upsert_work_item(store: Store, **candidate_fields: Any) -> dict:
    """Contract-validated filing. Returns
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

    row_fields = _row_fields_from_candidate(store, candidate)
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
