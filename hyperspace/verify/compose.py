# Vendored from the Nova Caelum graph_library primitives/completion/compose.py, 2026-09-26.
# Adapted for hyperspace-engine; see THIRD_PARTY_NOTICES.md.
"""Step 5 — composition, and the run state object that makes this a graph.

The rule fits in one table (spec §6):

    any step refused    -> refused      (names the step, the item, the repair)
    else any uncertain  -> unverifiable (the user's, with the trail)
    else                -> done

Refused dominates uncertain so a definitive failure never lands on the user. A
discharged landing check never rescues a criteria refusal — presence is a
floor, never a ceiling. `manual` binds: it discharges
only against a user-attested (`Deps.user_identity`), exact-statement
`ManualAttestation` (`hyperspace/verify/claim.py`); unattested, it is
`uncertain`, so an un-inspected `manual` criterion never lets a row reach
`done` by itself.

`VerificationState` mirrors `contracts/run.py::MachineRun` field-for-field
where semantics match (`run_id`, `status`, `current_step`≈`current_node`,
`error`, `final_result`) so the two can converge later without a rewrite. It is
written at EVERY junction ("state tracking is literally what makes it a graph
not a loop"), to the local store's `verifier_runs` row, because a run whose state only reaches disk at the end
recovers from nothing and explains nothing.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

Outcome = Literal["done", "refused", "unverifiable", "already_done"]
StepStatus = Literal["passed", "refused", "uncertain", "skipped"]

JUNCTIONS = (
    "received", "vetted", "criteria_checked", "landing_checked", "comprehended", "composed",
)


class StepVerdict(BaseModel):
    step: str
    status: StepStatus
    detail: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class VerificationState(BaseModel):
    run_id: str
    project: str
    external_id: str
    status: str = "running"                 # "running" | Outcome
    current_step: str = "received"
    trail: list[dict[str, str]] = Field(default_factory=list)   # [{step, at}]
    steps: dict[str, StepVerdict] = Field(default_factory=dict)
    error: str | None = None
    final_result: dict[str, Any] | None = None
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    state_path: str | None = None


class StateWriter(Protocol):
    def write(self, state: VerificationState) -> None: ...


class StoreStateWriter:
    """Upserts the run's `verifier_runs` row at every junction — one committed
    SQLite write per junction, the same atomic-per-junction discipline the
    canonical JSON writer kept. The whole `VerificationState` (trail, steps,
    final result) is stored in the row's `steps` column. Losing a write must
    never kill a run that has already been paid for, so a store error is
    swallowed, exactly as the canonical writer swallowed `OSError`."""

    def __init__(self, store: Any, judge_name: str) -> None:
        self.store = store
        self.judge_name = judge_name

    def ref_for(self, run_id: str) -> str:
        return f"{self.store.path}#verifier_runs/{run_id}"

    def write(self, state: VerificationState) -> None:
        state.updated_at = datetime.now(timezone.utc).isoformat()
        state.state_path = self.ref_for(state.run_id)
        finished = state.status != "running"
        fields = dict(
            id=state.run_id, started_at=state.started_at,
            finished_at=state.updated_at if finished else None,
            outcome=state.status if finished else None, judge=self.judge_name,
            steps=state.model_dump(mode="json"), error=state.error,
        )
        try:
            try:
                self.store.record_verifier_run(state.external_id, state.project, **fields)
            except sqlite3.IntegrityError:
                # `project_code` references `projects(code)`: a claim naming an
                # unknown project still gets its run recorded, unattached.
                self.store.record_verifier_run(state.external_id, None, **fields)
        except sqlite3.Error:
            pass


def enter(state: VerificationState, step: str, writer: StateWriter) -> None:
    """Cross a junction: record it, persist it."""
    state.current_step = step
    state.trail.append({"step": step, "at": datetime.now(timezone.utc).isoformat()})
    writer.write(state)


def record(state: VerificationState, verdict: StepVerdict, writer: StateWriter) -> None:
    state.steps[verdict.step] = verdict
    writer.write(state)


def compose(steps: dict[str, StepVerdict]) -> tuple[Outcome, str]:
    """The table, executed. Order of the checks IS the rule."""
    refused = [s for s in steps.values() if s.status == "refused"]
    if refused:
        first = refused[0]
        return "refused", f"{first.step}: {first.detail}"
    uncertain = [s for s in steps.values() if s.status == "uncertain"]
    if uncertain:
        first = uncertain[0]
        return "unverifiable", f"{first.step}: {first.detail}"
    return "done", "every step passed"


def finish(state: VerificationState, outcome: Outcome, reason: str, writer: StateWriter,
           result: dict[str, Any] | None = None, error: str | None = None) -> VerificationState:
    state.status = outcome
    state.current_step = outcome
    state.trail.append({"step": outcome, "at": datetime.now(timezone.utc).isoformat()})
    state.final_result = {"outcome": outcome, "reason": reason, **(result or {})}
    state.error = error
    writer.write(state)
    return state
