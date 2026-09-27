# Vendored from the Nova Caelum graph_library primitives/completion/{pipeline,resolve}.py
# and contracts/commit.py::criteria_fingerprint, 2026-09-26. Adapted for hyperspace-engine; see THIRD_PARTY_NOTICES.md.
"""`Deps` — the verification graph's seam — and `local_deps`, its local-store backend.

Everything with a side effect or a judgment is injected through `Deps`, so the
whole graph runs in a test with a temp store, a temp git checkout and a scripted
judge — and the production wiring is one function. The canonical backend reached
an ops server under two bearer identities; this one is the local SQLite store:

  read_row          -> Store.get_work_item, mapped to `RowFacts`
  resolve_criteria  -> Store.resolve_criteria(row.acceptance_criteria_ref), parsed
                       into `AcceptanceCriterion` models, fingerprinted, with the
                       FILING's `filed_at`
  commit            -> Store.set_work_item_state(id, "done", completed_by="hyperspace-verifier")
  readback_state    -> Store.get_work_item(...)["state"]
  judge_*           -> the `Judge` instance
  writer            -> StoreStateWriter (the `verifier_runs` row)
"""
import hashlib
import json
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..contracts.candidate import AcceptanceCriterion
from .compose import StateWriter, StoreStateWriter

COMMITTER_IDENTITY = "hyperspace-verifier"
DEFAULT_USER_IDENTITY = "user"

REPAIR_CRITERIA = (
    "Repair the criteria FIRST with an ordinary (non-`done`) upsert_work_item "
    "carrying acceptance_criteria + update_acceptance_criteria=true, then call "
    "complete_workitem again."
)


class BackendError(RuntimeError):
    """A row or its criteria could not be read. Takes the place of the canonical
    `OpsError`: the message is the repair, and the graph routes it to
    `unverifiable`."""


@dataclass
class RowFacts:
    id: str
    external_id: str
    project: str
    name: str
    type: str
    state: str | None
    description: str | None
    created_at: datetime
    acceptance_criteria_ref: str | None
    acceptance_criteria_digest: str | None

    @property
    def task_statement(self) -> str:
        body = (self.description or "").strip()
        return f"{self.name.strip()}\n\n{body}" if body else self.name.strip()


@dataclass
class TypedCriteria:
    criteria: list[AcceptanceCriterion]
    fingerprint: str
    run_id: str            # the filing id the row's ref names (canonical: the ledger run id)
    item_id: str           # the external_id the ref names
    filed_at: datetime     # the FILING's timestamp — the start of the delta window


@dataclass
class Deps:
    vault_root: Path  # canonical field name, kept; always equal to `project_root` here
    read_row: Callable[[str, str | None], RowFacts]
    resolve_criteria: Callable[[RowFacts], TypedCriteria]
    judge_criteria: Callable[[str, list[Any]], Awaitable[tuple[Any, dict]]]
    judge_evidence: Callable[[str, list[Any], list[str]], Awaitable[tuple[Any, dict]]]
    commit: Callable[[dict], dict]
    readback_state: Callable[[str, str | None], str | None]
    writer: StateWriter
    model: str | None = None
    project_root: Path = Path(".")
    user_identity: str = DEFAULT_USER_IDENTITY
    judge_name: str = "none"


def criteria_fingerprint(criteria: list[AcceptanceCriterion]) -> str:
    """A stable, order-sensitive hash of what the criteria ASSERT
    (`source_template` excluded — it records wording provenance, not the check)."""
    payload = [
        {"statement": c.statement.strip(), "verification": c.verification.model_dump(mode="json")}
        for c in criteria
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_ts(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def row_facts(payload: dict) -> RowFacts:
    return RowFacts(
        id=str(payload.get("id")),
        external_id=str(payload.get("external_id")),
        project=str(payload.get("project_code") or payload.get("project") or ""),
        name=str(payload.get("name") or ""),
        type=str(payload.get("type") or ""),
        state=payload.get("state"),
        description=payload.get("description"),
        created_at=_parse_ts(payload.get("created_at")),
        acceptance_criteria_ref=payload.get("acceptance_criteria_ref"),
        acceptance_criteria_digest=payload.get("acceptance_criteria"),
    )


def _filing_id(ref: str) -> tuple[str, str]:
    prefix = "graph://filing/"
    if not ref.startswith(prefix):
        raise BackendError(f"acceptance_criteria_ref is not a graph://filing/ URI: {ref!r}. {REPAIR_CRITERIA}")
    filing_id, _, tail = ref[len(prefix):].partition("/item/")
    item = tail.split("#", 1)[0]
    if not filing_id or not item:
        raise BackendError(f"acceptance_criteria_ref {ref} names no filing or no item. {REPAIR_CRITERIA}")
    return filing_id, item


def read_user_identity(project_root: Path) -> str:
    """`user = "..."` from `<project_root>/.hyperspace/config.toml`, else "user"."""
    path = project_root / ".hyperspace" / "config.toml"
    try:
        with path.open("rb") as fh:
            value = tomllib.load(fh).get("user")
    except (OSError, tomllib.TOMLDecodeError):
        return DEFAULT_USER_IDENTITY
    return value.strip() if isinstance(value, str) and value.strip() else DEFAULT_USER_IDENTITY


def _default_project_root(store: Any) -> Path:
    db = Path(store.path).resolve()
    return db.parent.parent if db.parent.name == ".hyperspace" else Path.cwd().resolve()


def local_deps(store: Any, judge: Any, *, project_root: Path | None = None,
               user_identity: str | None = None) -> Deps:
    """The graph's backend over the local store. `project_root` defaults to the
    directory holding the store's `.hyperspace/`; `user_identity` defaults to
    `.hyperspace/config.toml`'s `user`, else "user"."""
    root = Path(project_root).resolve() if project_root is not None else _default_project_root(store)
    identity = user_identity or read_user_identity(root)

    def _get(external_id: str, project: str | None) -> dict | None:
        row = store.get_work_item(external_id=external_id, project_code=project) if project else None
        # A bare lookup still finds a row filed under a DIFFERENT project, so the
        # vet step can refuse the mismatch rather than report the row missing.
        return row or store.get_work_item(external_id=external_id)

    def read_row(external_id: str, project: str | None = None) -> RowFacts:
        payload = _get(external_id, project)
        if not payload:
            raise BackendError(f"no work item {external_id!r} in this project's store")
        return row_facts(payload)

    def resolve_criteria(row: RowFacts) -> TypedCriteria:
        if not row.acceptance_criteria_ref:
            raise BackendError(
                "this row carries no acceptance_criteria_ref, so its typed criteria are "
                f"not recoverable and there is nothing to verify against. {REPAIR_CRITERIA}"
            )
        filing_id, item = _filing_id(row.acceptance_criteria_ref)
        filing = store.get_filing(filing_id)
        if filing is None:
            raise BackendError(f"the filing this ref points at ({filing_id}) does not exist. {REPAIR_CRITERIA}")
        try:
            stored = store.resolve_criteria(row.acceptance_criteria_ref)
        except ValueError as exc:
            raise BackendError(f"{exc}. {REPAIR_CRITERIA}") from None
        if not isinstance(stored, list) or not stored:
            raise BackendError(f"the filing holds no typed acceptance criteria for this row. {REPAIR_CRITERIA}")
        typed = [AcceptanceCriterion(**c) for c in stored]
        # Landing measures the delta from the FILING's `filed_at`, not the row's
        # `created_at`: a criteria update mints a new filing, and the delta
        # window restarts from it — work done before the criteria it is judged
        # against were filed cannot discharge them.
        return TypedCriteria(criteria=typed, fingerprint=criteria_fingerprint(typed),
                             run_id=filing_id, item_id=item, filed_at=_parse_ts(filing["filed_at"]))

    def commit(verified_completion: dict) -> dict:
        row = _get(verified_completion["external_id"], verified_completion["project"])
        if row is None:
            raise BackendError(f"no work item {verified_completion['external_id']!r} to flip")
        flipped = store.set_work_item_state(row["id"], "done", completed_by=COMMITTER_IDENTITY)
        return {"id": flipped["id"], "state": flipped["state"], "completed_by": flipped["completed_by"]}

    def readback_state(external_id: str, project: str | None = None) -> str | None:
        row = _get(external_id, project)
        return row.get("state") if row else None

    return Deps(
        vault_root=root,
        read_row=read_row,
        resolve_criteria=resolve_criteria,
        judge_criteria=judge.judge_criteria,
        judge_evidence=judge.judge_evidence,
        commit=commit,
        readback_state=readback_state,
        writer=StoreStateWriter(store, judge.name),
        model=None,
        project_root=root,
        user_identity=identity,
        judge_name=judge.name,
    )
