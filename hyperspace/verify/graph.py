# Vendored from the Nova Caelum graph_library primitives/completion/pipeline.py, 2026-09-26.
# Adapted for hyperspace-engine; see THIRD_PARTY_NOTICES.md.
"""`complete_workitem` — the five-step closure pipeline as a pydantic graph.

Vet → CriteriaQuality → Landing → EvidenceJudge → Commit (canonical numbering
1 → 3 → 4 → 2 → 5), state written to the store at every junction.

Order is load-bearing: the cheap criteria gate runs before the landing check and
the evidence call, so a bad-criteria row never spends a model call on evidence
and the evidence judge cannot be anchored to a criterion the criteria step is
about to reject.

Each node body is the corresponding block of the canonical `complete_workitem`,
moved, not rewritten. The one intended divergence is the `none` ruling: when
`deps.judge_name == "none"` the two semantic nodes record `skipped` without
calling the judge, and — because `compose()` passes `skipped` through — the row
closes `done` iff Landing discharged every criterion, `unverifiable` if Landing
left any `uncertain`. Keyless closure of deterministic criteria.

No `from __future__ import annotations` here: pydantic-graph reads each node's
`run` return annotation at runtime to infer the edges.
"""
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_graph import BaseNode, End, GraphBuilder, GraphRunContext, StepContext

from .claim import CompletionClaim, resolve_touched_path
from .compose import StepVerdict, VerificationState, compose, enter, finish, record
from .deps import Deps, RowFacts, TypedCriteria
from .landing import LandingResult, landing_check

NO_JUDGE = "no judge configured"
MAX_CURRENT_CHARS = 30_000
MAX_DELTA_CHARS = 20_000


# ─────────────────────────────────────────────────────────────────────────────
# Helpers (canonical pipeline.py, moved)
# ─────────────────────────────────────────────────────────────────────────────


async def _with_retry(call, *args, attempts: int = 2):
    """A judge failure (transport, provider, `JudgeUnavailable`) gets ONE retry
    before it becomes `uncertain` (bounded 2)."""
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return await call(*args)
        except Exception as exc:  # noqa: BLE001 — recorded, never swallowed
            last = exc
    assert last is not None
    raise last


def _landing_payload(landing: LandingResult) -> dict:
    return {
        "passed": landing.passed,
        "discharged_count": landing.discharged_count,
        "verdicts": [
            {"statement": v.statement, "kind": v.kind, "discharged": v.discharged,
             "failed": v.failed, "uncertain": v.uncertain, "evidence": v.evidence[:600]}
            for v in landing.verdicts
        ],
        "roots": [str(r) for r in landing.roots],
        "unclaimed_changes": landing.unclaimed,
    }


def _judged_criteria(criteria: list[Any], landing: LandingResult) -> list[Any]:
    """Non-`manual` criteria the evidence judge should assess. `manual` binds at
    landing and is never handed to the judge; neither is a `command_check`
    landing already DISCHARGED (a command's exit code produces no file delta, so
    the judge would see zero evidence for a criterion that already passed).
    Relies on `landing_check()` emitting exactly one verdict per criterion, in
    order, after any `manual_attestation`-mismatch records."""
    per_criterion = [v for v in landing.verdicts if v.kind != "manual_attestation"]
    assert len(per_criterion) == len(criteria), (
        "landing_check() must emit exactly one verdict per criterion, order-preserved"
    )
    judged = []
    for c, v in zip(criteria, per_criterion):
        if c.verification.kind == "manual":
            continue
        if c.verification.kind == "command_check" and v.discharged:
            continue
        judged.append(c)
    return judged


def render_observation(path_label: str, delta: Any) -> str:
    """One observation block from a `PathDelta` — vendored from the canonical
    `judges/semantics_agent.py` (not a model call; the judge row's runners
    consume the rendered blocks)."""
    # One separator style for the judge on every OS: the criteria it
    # compares against name paths with forward slashes.
    head = f"--- {Path(path_label).as_posix()}"
    if getattr(delta, "repo", None):
        head += f" (repo: {delta.repo})"
    head += " ---"
    if not delta.exists_now:
        state = "DOES NOT EXIST"
        if delta.changed_since_filing:
            state += f" — removed since filing ({delta.how})"
        return f"{head}\n{state}"
    lines = [head, f"exists: yes · changed since filing: "
             f"{'yes' if delta.changed_since_filing else 'NO'} ({delta.how})"]
    if delta.changed_since_filing and delta.diff:
        lines.append("DELTA since filing:")
        lines.append(delta.diff[:MAX_DELTA_CHARS])
    current = delta.current or ""
    lines.append("CURRENT content:")
    lines.append(current[:MAX_CURRENT_CHARS] if current else "(empty)")
    return "\n".join(lines)


def _observations(landing: LandingResult, criteria: list[Any], touched: list[tuple[Path, str]]) -> list[str]:
    blocks: list[str] = []
    seen: set[str] = set()
    # Criterion-named paths first (in criterion order), then the claim's touched paths.
    ordered: list[str] = []
    for v in landing.verdicts:
        if v.path and v.path in landing.deltas and v.path not in seen:
            seen.add(v.path); ordered.append(v.path)
    for p, _ in touched:
        key = str(p)
        if key in landing.deltas and key not in seen:
            seen.add(key); ordered.append(key)
    for key in ordered:
        blocks.append(render_observation(key, landing.deltas[key]))
    return blocks


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class VerifyState:
    claim: CompletionClaim
    state: VerificationState
    row: RowFacts | None = None
    typed: TypedCriteria | None = None
    touched: list[tuple[Path, str]] = field(default_factory=list)
    landing: LandingResult | None = None
    cq: Any = None                      # CriteriaJudgment, or None when skipped
    judgment_payload: dict | None = None
    model_calls: int = 0


def _out(ctx: GraphRunContext["VerifyState", Deps], outcome: str, reason: str, **extra: Any) -> End[dict]:
    s, claim = ctx.state.state, ctx.state.claim
    finish(s, outcome, reason, ctx.deps.writer, result={k: v for k, v in extra.items() if k != "error"},
           error=extra.get("error"))
    return End({
        "outcome": outcome, "reason": reason, "run_id": s.run_id,
        "external_id": claim.external_id, "state_path": s.state_path,
        "trail": [t["step"] for t in s.trail],
        "steps": {k: {"status": v.status, "detail": v.detail[:800], **({"data": v.data} if v.data else {})}
                  for k, v in s.steps.items()},
        "model_calls": ctx.state.model_calls,
        **extra,
    })


def _skip_no_judge(ctx: GraphRunContext["VerifyState", Deps], step: str) -> bool:
    """The `none` ruling: no judge configured → the semantic step is `skipped`,
    decided BEFORE any judge call and before any short-circuit on its result."""
    if ctx.deps.judge_name != "none":
        return False
    record(ctx.state.state, StepVerdict(step=step, status="skipped", detail=NO_JUDGE), ctx.deps.writer)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# The five nodes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Vet(BaseNode[VerifyState, Deps, dict]):
    """Step 1 — the row exists and is not done; its typed criteria resolve;
    every touched path is present/absent as claimed. Zero model calls."""

    async def run(self, ctx: GraphRunContext[VerifyState, Deps]) -> "CriteriaQuality | End[dict]":
        st, deps, claim = ctx.state.state, ctx.deps, ctx.state.claim
        w = deps.writer
        try:
            row = deps.read_row(claim.external_id, claim.project)
        except Exception as exc:  # noqa: BLE001 — a backend failure is uncertainty
            record(st, StepVerdict(step="vet", status="uncertain", detail=f"row read failed: {exc}"), w)
            return _out(ctx, "unverifiable", f"vet: could not read the row — {exc}")
        ctx.state.row = row
        if row.state == "done":
            record(st, StepVerdict(step="vet", status="passed", detail="row already done"), w)
            return _out(ctx, "already_done", "the row is already `done`; nothing to verify", readback_state="done")
        if row.project and row.project != claim.project:
            record(st, StepVerdict(step="vet", status="refused",
                                   detail=f"project: the row belongs to {row.project!r}, not {claim.project!r}"), w)
            return _out(ctx, "refused", st.steps["vet"].detail)
        try:
            typed = deps.resolve_criteria(row)
        except Exception as exc:  # noqa: BLE001
            record(st, StepVerdict(step="vet", status="uncertain", detail=str(exc)), w)
            return _out(ctx, "unverifiable", f"vet: {exc}")
        ctx.state.typed = typed

        touched = [(resolve_touched_path(t.path, deps.project_root), t.effect) for t in claim.touched]
        ctx.state.touched = touched
        missing = [str(p) for p, eff in touched if eff in ("created", "modified") and not p.exists()]
        lingering = [str(p) for p, eff in touched if eff == "deleted" and p.exists()]
        if missing or lingering:
            parts = []
            if missing:
                parts.append("claimed created/modified but absent: " + ", ".join(missing))
            if lingering:
                parts.append("claimed deleted but still present: " + ", ".join(lingering))
            detail = "; ".join(parts) + ". Fix the touched list or finish the work, then resubmit."
            record(st, StepVerdict(step="vet", status="refused", detail=detail), w)
            return _out(ctx, "refused", f"vet: {detail}")
        record(st, StepVerdict(step="vet", status="passed",
                               detail=f"{len(typed.criteria)} typed criteria resolved; {len(touched)} touched path(s) present",
                               data={"criteria_fingerprint": typed.fingerprint, "run_ref": typed.run_id}), w)
        enter(st, "vetted", w)
        return CriteriaQuality()


@dataclass
class CriteriaQuality(BaseNode[VerifyState, Deps, dict]):
    """Step 3 — are the criteria about THIS task and observable? Runs before the
    world is looked at."""

    async def run(self, ctx: GraphRunContext[VerifyState, Deps]) -> "Landing | End[dict]":
        st, deps = ctx.state.state, ctx.deps
        w = deps.writer
        if _skip_no_judge(ctx, "criteria"):
            enter(st, "criteria_checked", w)
            return Landing()
        row, typed = ctx.state.row, ctx.state.typed
        try:
            cq, cq_usage = await _with_retry(deps.judge_criteria, row.task_statement, typed.criteria)
            ctx.state.model_calls += 1
        except Exception as exc:  # model/transport failure is uncertainty, never a pass
            record(st, StepVerdict(step="criteria", status="uncertain",
                                   detail=f"criteria judge failed: {type(exc).__name__}: {str(exc)[:300]}"), w)
            return _out(ctx, "unverifiable", st.steps["criteria"].detail)
        ctx.state.cq = cq
        cq_data = {"acceptable": cq.acceptable, "uncertain": cq.uncertain, "reason": cq.reason,
                   "criteria": [c.model_dump() for c in cq.criteria], "usage": cq_usage}
        if cq.uncertain:
            record(st, StepVerdict(step="criteria", status="uncertain", detail=cq.reason, data=cq_data), w)
        elif not cq.acceptable:
            bad = [c for c in cq.criteria if not (c.relevant and c.assessable)]
            detail = ("criteria do not test this task — " +
                      "; ".join(f"{c.statement!r}: {c.reason}" for c in bad) +
                      ". Repair with a non-`done` upsert_work_item carrying acceptance_criteria + update_acceptance_criteria=true, then resubmit.")
            record(st, StepVerdict(step="criteria", status="refused", detail=detail, data=cq_data), w)
            return _out(ctx, "refused", f"criteria: {detail}")
        else:
            record(st, StepVerdict(step="criteria", status="passed", detail=cq.reason, data=cq_data), w)
        enter(st, "criteria_checked", w)
        return Landing()


@dataclass
class Landing(BaseNode[VerifyState, Deps, dict]):
    """Step 4 — the landing check: delta since the FILING, deterministic."""

    async def run(self, ctx: GraphRunContext[VerifyState, Deps]) -> "EvidenceJudge | End[dict]":
        st, deps, claim, typed = ctx.state.state, ctx.deps, ctx.state.claim, ctx.state.typed
        w = deps.writer
        landing = landing_check(typed.criteria, project_root=deps.project_root, touched=ctx.state.touched,
                                filed_at=typed.filed_at, manual_attestations=claim.manual_attestations,
                                user_identity=deps.user_identity)
        ctx.state.landing = landing
        lp = _landing_payload(landing)
        if landing.any_failed:
            failed = [v for v in landing.verdicts if v.failed]
            detail = "; ".join(f"{v.statement!r} [{v.kind}]: {v.evidence}" for v in failed)
            record(st, StepVerdict(step="landing", status="refused", detail=detail, data=lp), w)
            return _out(ctx, "refused", f"landing: {detail}", unclaimed_changes=landing.unclaimed)
        if not landing.any_discharged:
            detail = ("zero predicates discharged — " +
                      "; ".join(f"{v.statement!r}: {v.evidence}" for v in landing.verdicts if not v.manual))
            record(st, StepVerdict(step="landing", status="uncertain", detail=detail, data=lp), w)
        elif landing.any_uncertain:
            unc = [v for v in landing.verdicts if v.uncertain]
            record(st, StepVerdict(step="landing", status="uncertain",
                                   detail="; ".join(f"{v.statement!r}: {v.evidence}" for v in unc), data=lp), w)
        else:
            record(st, StepVerdict(step="landing", status="passed",
                                   detail=f"{landing.discharged_count} predicate(s) discharged against the delta, none failed",
                                   data=lp), w)
        enter(st, "landing_checked", w)
        return EvidenceJudge()


@dataclass
class EvidenceJudge(BaseNode[VerifyState, Deps, dict]):
    """Step 2 — does the observed delta establish each criterion, and is the
    task's stated outcome realized? `manual` criteria bind at landing and are
    never handed to the judge."""

    async def run(self, ctx: GraphRunContext[VerifyState, Deps]) -> "Commit | End[dict]":
        st, deps, landing, typed = ctx.state.state, ctx.deps, ctx.state.landing, ctx.state.typed
        w = deps.writer
        if _skip_no_judge(ctx, "evidence"):
            ctx.state.judgment_payload = {"accepted": None, "outcome_realized": None, "reason": NO_JUDGE,
                                          "criteria": []}
            enter(st, "comprehended", w)
            return Commit()
        judged = _judged_criteria(typed.criteria, landing)
        if not landing.any_discharged and landing.any_uncertain:
            # Nothing discharged and landing could not decide: no evidence call
            # can make this `done` — skip the spend.
            record(st, StepVerdict(step="evidence", status="skipped",
                                   detail="skipped: the landing check discharged nothing and was uncertain; "
                                          "an evidence judgment cannot make this `done`"), w)
            enter(st, "comprehended", w)
            outcome, reason = compose(st.steps)
            enter(st, "composed", w)
            return _out(ctx, outcome, reason, unclaimed_changes=landing.unclaimed)
        if judged:
            try:
                judgment, ev_usage = await _with_retry(
                    deps.judge_evidence, ctx.state.row.task_statement, judged,
                    _observations(landing, judged, ctx.state.touched))
                ctx.state.model_calls += 1
            except Exception as exc:
                record(st, StepVerdict(step="evidence", status="uncertain",
                                       detail=f"evidence judge failed: {type(exc).__name__}: {str(exc)[:300]}"), w)
                return _out(ctx, "unverifiable", st.steps["evidence"].detail, unclaimed_changes=landing.unclaimed)
            ev_data = {"accepted": judgment.accepted, "outcome_realized": judgment.outcome_realized,
                       "uncertain": judgment.uncertain, "reason": judgment.reason,
                       "criteria": [c.model_dump() for c in judgment.criteria], "usage": ev_usage}
            if judgment.uncertain:
                record(st, StepVerdict(step="evidence", status="uncertain", detail=judgment.reason, data=ev_data), w)
            elif not judgment.accepted:
                und = [c for c in judgment.criteria if not c.discharged]
                detail = judgment.reason
                if und:
                    detail += " — undischarged: " + "; ".join(c.statement for c in und)
                if not judgment.outcome_realized:
                    detail += " — the task's stated outcome is not realized in the observed change"
                record(st, StepVerdict(step="evidence", status="refused", detail=detail, data=ev_data), w)
                return _out(ctx, "refused", f"evidence: {detail}", unclaimed_changes=landing.unclaimed)
            else:
                record(st, StepVerdict(step="evidence", status="passed", detail=judgment.reason, data=ev_data), w)
            ctx.state.judgment_payload = {"accepted": judgment.accepted, "outcome_realized": judgment.outcome_realized,
                                          "reason": judgment.reason,
                                          "criteria": [c.model_dump() for c in judgment.criteria]}
        else:
            # Every non-manual criterion was a command_check landing already
            # discharged; no file-delta evidence exists for a judge to assess.
            detail = ("skipped: every remaining criterion was a command_check already discharged "
                      "deterministically by the landing step; no file-delta evidence exists for the "
                      "judge to assess")
            record(st, StepVerdict(step="evidence", status="skipped", detail=detail), w)
            ctx.state.judgment_payload = {"accepted": True, "outcome_realized": True, "reason": detail, "criteria": []}
        enter(st, "comprehended", w)
        return Commit()


@dataclass
class Commit(BaseNode[VerifyState, Deps, dict]):
    """Step 5 — compose, commit, read back. Success is the readback, never the
    commit's own return value."""

    async def run(self, ctx: GraphRunContext[VerifyState, Deps]) -> End[dict]:
        st, deps, claim, landing, typed = (ctx.state.state, ctx.deps, ctx.state.claim,
                                           ctx.state.landing, ctx.state.typed)
        w = deps.writer
        outcome, reason = compose(st.steps)
        enter(st, "composed", w)
        if outcome != "done":
            return _out(ctx, outcome, reason, unclaimed_changes=landing.unclaimed)

        cq = ctx.state.cq
        verified_completion = {
            "project": claim.project, "external_id": claim.external_id,
            "idempotency_key": claim.idempotency_key, "verification_run_id": st.run_id,
            "proposer_identity": claim.proposer_identity, "proposer_surface": claim.proposer_surface,
            "criteria_fingerprint": typed.fingerprint, "outcome": "done",
            "touched": [t.model_dump() for t in claim.touched],
            "landing": {"discharged_count": landing.discharged_count,
                        "verdicts": [{"statement": v.statement, "kind": v.kind, "discharged": v.discharged,
                                      "evidence": v.evidence[:2000]} for v in landing.verdicts]},
            "criteria_quality": ({"acceptable": cq.acceptable, "reason": cq.reason} if cq is not None
                                 else {"acceptable": None, "reason": NO_JUDGE}),
            "judgment": ctx.state.judgment_payload,
            "unclaimed_changes": landing.unclaimed[:50],
            "model": deps.model,
            "judge": deps.judge_name,
        }
        try:
            server_payload = deps.commit(verified_completion)
        except Exception as exc:  # noqa: BLE001
            record(st, StepVerdict(step="commit", status="uncertain", detail=f"the store refused the flip: {exc}"), w)
            return _out(ctx, "unverifiable", f"commit: the store refused the flip — {exc}", error=str(exc))
        readback = deps.readback_state(claim.external_id, claim.project)
        if readback != "done":
            record(st, StepVerdict(step="commit", status="uncertain",
                                   detail=f"the store answered but readback shows state={readback!r}, not done"), w)
            return _out(ctx, "unverifiable", st.steps["commit"].detail, readback_state=readback,
                        error="readback mismatch")
        record(st, StepVerdict(step="commit", status="passed", detail="row flipped to done; readback confirms",
                               data={"store": server_payload}), w)
        return _out(ctx, "done", "verified against the delta and read back as done", readback_state=readback,
                    unclaimed_changes=landing.unclaimed)


# ─────────────────────────────────────────────────────────────────────────────
# The graph
# ─────────────────────────────────────────────────────────────────────────────

_builder = GraphBuilder(name="verification_graph", state_type=VerifyState, deps_type=Deps, output_type=dict)


@_builder.step
async def begin(ctx: StepContext[VerifyState, Deps, None]) -> Vet:
    return Vet()


_builder.add(
    _builder.node(Vet),
    _builder.node(CriteriaQuality),
    _builder.node(Landing),
    _builder.node(EvidenceJudge),
    _builder.node(Commit),
    _builder.edge_from(_builder.start_node).to(begin),
)

verification_graph = _builder.build()


async def complete_workitem(claim: CompletionClaim, deps: Deps) -> dict:
    """Run the verification graph for one claim. Returns exactly one of
    `done | refused | unverifiable | already_done`, with the trail, per-step
    verdicts and the run id; never raises for a judge or backend failure."""
    run_id = str(uuid.uuid4())
    state = VerificationState(run_id=run_id, project=claim.project, external_id=claim.external_id)
    enter(state, "received", deps.writer)
    return await verification_graph.run(state=VerifyState(claim=claim, state=state), deps=deps)
