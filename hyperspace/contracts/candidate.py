# Vendored from the Nova Caelum graph_library contracts, 2026-09-26.
# Adapted for the hyperspace-engine plugin; see bin/PORT_NOTES.md.
"""`CandidateWorkItem` — the agent proposal contract (§6.1).

**Independent of the live row-write contract by design.** `WorkItemUpsertArgs` in
the graph service's row-contract module is the row contract; reusing it by
inheritance would create two contradictory representations (`description`
inherited while `specification` claims to replace it) and would accidentally
subject the trusted console to agent-only requirements. Shared field shapes are
kept honest by a parity test, never by a base class.

Import-portability (§3.2): this module must import cleanly under
`pydantic==2.10.3` with **no `pydantic-graph` installed**, because the graph
service imports it at that pin to validate agent ingress inline (§5.2) — one contract,
two invocation sites, no second definition. The API surface used here
(`BaseModel`, `Field` with length bounds, `Literal`, `field_validator`,
`model_validator`, `model_config` with `extra: "forbid"`) is stable across
2.10 → 2.13, and that is an exit gate rather than a belief: the corpus runs
under both pins.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import (
    CommandCheckId,
    EffortLevel,
    FileStateAssertion,
    UncertaintyKind,
    WorkItemState,
    WorkItemType,
)


class _StrictArgs(BaseModel):
    model_config = {"extra": "forbid"}


# ─────────────────────────────────────────────────────────────────────────────
# Placeholder detection — deterministic, and CORPUS-CALIBRATED.
# ─────────────────────────────────────────────────────────────────────────────

# §6.1: "Deterministic, corpus-calibrated. Lives in code, not in a rule an agent
# is asked to follow."
#
# The failure this catches is not emptiness — a length floor already stops that.
# It is *emptiness dressed as content*: three fields that each clear forty
# characters while asserting nothing. §6.1 names it directly — "a character floor
# is satisfied by padding, while the observed failure was emptiness dressed as a
# title."
#
# CALIBRATION SET. These live in the corpus and both directions are asserted by
# `corpus/deterministic/per_primitive/validator-placeholder-*.json`:
#
#   MUST match (rejected):
#     "TODO - to be determined once the scope of this work has been established."
#     "TBD. This matters and will be filled in later when there is more time."
#     "See the description field for further context on this item."
#
#   MUST NOT match (accepted):
#     "The corpus harness must run before any venv exists, so a third-party
#      import would make it unrunnable at P1."
#     "graph_library/corpus/harness/vocab.py module docstring."
#     ...and every `specification` block in the twenty benchmark cases.
#
# Widening this pattern without running the corpus is how a legitimate proposal
# starts getting rejected for looking vaguely like a placeholder. The corpus is
# the calibration instrument; use it.
#
# Deliberately NOT included: a bare leading "unknown". "Unknown migrations are
# applied in production" is a real problem statement, and catching it would trade
# a false negative for a false positive on exactly the class of finding this
# system exists to surface.
_PLACEHOLDER_PREFIXES = (
    r"todo\b",
    r"tbd\b",
    r"fixme\b",
    r"xxx\b",
    r"placeholder\b",
    r"n/?a\b",
    r"see\s+(the\s+)?(description|above|below|attached|other\s+field)",
    r"to\s+be\s+(determined|decided|filled|written|scoped)",
)

_PLACEHOLDER_WHOLE = frozenset(
    {"tbd", "todo", "n/a", "na", "none", "unknown", "fixme", "xxx", "placeholder", "?", "-", ""}
)

_PLACEHOLDER_CONTAINS = (
    r"to\s+be\s+determined",
    r"will\s+be\s+filled\s+in\s+later",
    r"figure\s+(this\s+)?out\s+later",
)

_PLACEHOLDER_RE = re.compile(
    "|".join(f"(?:{p})" for p in _PLACEHOLDER_PREFIXES),
    re.IGNORECASE,
)

_CONTAINS_RE = re.compile(
    "|".join(f"(?:{p})" for p in _PLACEHOLDER_CONTAINS),
    re.IGNORECASE,
)


def is_placeholder(value: str) -> bool:
    """True when `value` is placeholder text rather than a specification."""
    reduced = value.strip()
    if reduced.strip(" .!?-–—").lower() in _PLACEHOLDER_WHOLE:
        return True
    if _PLACEHOLDER_RE.match(reduced):
        return True
    return bool(_CONTAINS_RE.search(reduced))


# ─────────────────────────────────────────────────────────────────────────────
# Specification — T1 and T2 in one model.
# ─────────────────────────────────────────────────────────────────────────────


class Specification(_StrictArgs):
    """The three questions `taskgraph-write` item 10 requires a description to
    answer, enforced as FIELDS so they cannot be answered by padding.

    The committer renders this into the row's `description`, so the filed row
    inherits the spec verbatim. That is T1 (empty-description filing) and T2
    (spec loss) closed by the same model: the row cannot exist without the spec,
    and the spec cannot be lost on the way to the row.
    """

    problem: str = Field(min_length=40, max_length=20_000)
    why_it_matters: str = Field(min_length=40, max_length=20_000)
    context_pointer: str = Field(min_length=20, max_length=20_000)

    @field_validator("problem", "why_it_matters", "context_pointer")
    @classmethod
    def not_placeholder(cls, v: str) -> str:
        if is_placeholder(v):
            raise ValueError("placeholder text is not a specification")
        return v.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Verification predicates — the proposer SELECTS, it does not SUPPLY.
# ─────────────────────────────────────────────────────────────────────────────


def _reject_path_traversal(v: str, *, field: str) -> str:
    """§15.2 shared: path traversal and symlink escape from the worktree are
    blocked at the contract rather than at the filesystem, because by the time
    a traversal reaches the filesystem the only thing standing between it and
    the parent tree is whichever code path happened to resolve it.

    Shared by `FileStateCheck.path` and `CommandCheck.target` — the latter had
    only the shell-metacharacter block (below) until
    ExternalReview_GraphMachine_2026-09-04's lint item 2 ("target outside the
    repo -> reject"): a `target` of `../../etc` or `/etc` contains no shell
    metacharacter and was passing uncaught.
    """
    if ".." in v.split("/") or v.startswith("/") or v.startswith("~"):
        raise ValueError(f"{field} must be repo-relative with no parent traversal")
    return v.strip()


class CommandCheck(_StrictArgs):
    kind: Literal["command_check"]
    check_id: CommandCheckId
    target: str | None = Field(default=None, max_length=500)

    @field_validator("target")
    @classmethod
    def target_is_not_a_command(cls, v: str | None) -> str | None:
        """`target` scopes an allowlisted check. It is never a command.

        §15.2 makes this a v1 security gate: agent proposals cannot carry raw
        shell predicates. Node 6 never shell-evaluates proposer text, so nothing
        downstream would execute this string — but a target containing shell
        metacharacters is a proposer ATTEMPTING to supply code, and refusing it
        here means the attempt is recorded as a rejection rather than silently
        ignored three nodes later.
        """
        if v is None:
            return None
        if any(ch in v for ch in ";|&`$><\n\r\\"):
            raise ValueError(
                "target must be a plain path or scope, not a command — shell "
                "metacharacters are not accepted"
            )
        return _reject_path_traversal(v, field="target")


class FileStateCheck(_StrictArgs):
    kind: Literal["file_state"]
    path: str = Field(min_length=1, max_length=1_000)
    assertion: FileStateAssertion
    expected: str | None = Field(default=None, max_length=4_000)

    @field_validator("path")
    @classmethod
    def no_traversal(cls, v: str) -> str:
        return _reject_path_traversal(v, field="path")


class DbReadbackCheck(_StrictArgs):
    kind: Literal["db_readback"]
    # An allowlisted REGISTRY KEY, never SQL. §6.1: the deterministic verifier
    # dispatches only through a code-owned registry and never accepts a raw SQL
    # target. The pattern is what makes "not in registry" the rejection message
    # rather than "malformed SQL" — the point is that no SQL is accepted here at
    # all, well-formed or not.
    query_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    expected: dict = Field(default_factory=dict)


class HttpReadbackCheck(_StrictArgs):
    kind: Literal["http_readback"]
    # An allowlisted host/route KEY, never a URL. Same reasoning as `query_id`.
    endpoint_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    expected_status: int = Field(ge=100, le=599)


class ManualCheck(_StrictArgs):
    kind: Literal["manual"]
    instruction: str = Field(min_length=10, max_length=2_000)


VerificationPredicate = Union[
    CommandCheck, FileStateCheck, DbReadbackCheck, HttpReadbackCheck, ManualCheck
]


class AcceptanceCriterion(_StrictArgs):
    """Observable acceptance data.

    The proposer selects a typed check; it does not supply code for the verifier
    to execute. Unknown checks are rejected or routed to manual/semantic
    verification — never executed by default.
    """

    statement: str = Field(min_length=10, max_length=2_000)
    verification: VerificationPredicate = Field(discriminator="kind")

    # Condition (c) of the ruling (ExternalReview_GraphMachine_2026-09-04):
    # "the resolved predicate is stored for audit alongside the original
    # template." Populated ONLY by `CandidateWorkItem`'s binder, keyed by the
    # verification field it changed (e.g. `{"path": "workspace/<date>.md"}`).
    # `None` when binding found nothing to substitute. SYSTEM-OWNED, not
    # proposer-settable: the binder unconditionally overwrites whatever a
    # caller sends here, because an audit field a proposer can forge is not
    # an audit field. See `CandidateWorkItem.bind_acceptance_criteria_tokens`.
    source_template: dict[str, str] | None = Field(default=None)


class SourceReference(_StrictArgs):
    """Mirror of the server's `SourceReference`. Parity-tested, not inherited."""

    uri: str = Field(min_length=1, max_length=2048)
    anchor: str | None = Field(default=None, max_length=512)


class Uncertainty(_StrictArgs):
    """One thing the proposer believes could make this candidate wrong.

    Answers exactly one question: "what would make this candidate wrong?" It is
    NOT a disclaimer, a hedge, or a confidence score — it is a check-first
    instruction handed to the attempter, which reads `uncertainty_notes` FIRST
    and runs each `check` before attempting anything (§9 node 5).
    """

    kind: UncertaintyKind
    detail: str = Field(min_length=1, max_length=2_000)  # what specifically, and why
    check: str = Field(min_length=1, max_length=2_000)   # the probe that would settle it


# ─────────────────────────────────────────────────────────────────────────────
# The binder — ExternalReview_GraphMachine_2026-09-04, accepted by the author.
#
# THE RULING: the correct amount of intelligence in the VERIFIER is zero.
# Criteria are translated into concrete predicates at FILING time; the
# translation is stored beside the original; evaluation stays deterministic.
# Three conditions make this sound:
#   (a) an LLM may perform the translation, never the evaluation — moot here,
#       this binder is plain string substitution, no LLM involved at all;
#   (b) the resolver must not be able to see the state it is about to check —
#       every token below resolves from data already present on THIS
#       candidate (or the wall clock at construction time), never from a
#       filesystem read or any later attempt/verification state;
#   (c) the resolved predicate is stored for audit alongside the original
#       template — `AcceptanceCriterion.source_template`, above.
#
# THE TOKEN TABLE. Closed set. An unknown token is refused at admission with
# this table printed in the error, so growing it is a deliberate, reviewed
# act — never a guess made to unblock one submission. Each entry names its
# deterministic source so "why does this token resolve to X" always has a
# one-line answer:
#   <date>     -> date.today() (UTC) at construction time — the filing date.
#   <run-id>   -> `idempotency_key`. The actual graph-machine run UUID is
#                 assigned by the graph service AFTER this object exists and is
#                 genuinely invisible to the binder by design (condition b);
#                 `idempotency_key` is the closest filing-time-stable
#                 identifier already carried on every candidate.
#   <slug>     -> `external_id`'s segment after the last `:` (the whole
#                 `external_id` when it carries no colon) — the
#                 `<project-code>:<slug>` convention `taskgraph-write`
#                 already requires.
#   <project>  -> `project`, verbatim.
# ─────────────────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"<([^<>]*)>")

SUPPORTED_TOKENS: dict[str, str] = {
    "date": "the filing date (UTC, YYYY-MM-DD)",
    "run-id": "this submission's idempotency_key",
    "slug": "external_id's segment after the last ':'",
    "project": "the candidate's project code",
}


def _supported_tokens_table() -> str:
    return "; ".join(f"<{name}> = {desc}" for name, desc in SUPPORTED_TOKENS.items())


def _slugify_for_path(value: str) -> str:
    """Path-safe rendering of a token value. `idempotency_key` in particular
    carries no character restriction at the field level, so a value bound
    into a `path` must be sanitized before insertion — a proposer's
    `idempotency_key` is not something the binder should trust as a path
    segment verbatim.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return cleaned or "unnamed"


def _derive_slug(external_id: str) -> str:
    return external_id.rsplit(":", 1)[-1] if ":" in external_id else external_id


def _filing_tokens(*, project: str, external_id: str, idempotency_key: str,
                    filing_date: date, path_mode: bool) -> dict[str, str]:
    render = _slugify_for_path if path_mode else (lambda s: s)
    return {
        "date": filing_date.isoformat(),  # already path-safe; no slugify needed
        "run-id": render(idempotency_key),
        "slug": render(_derive_slug(external_id)),
        "project": render(project),
    }


def _bind_token_string(value: str, tokens: dict[str, str], *, where: str) -> tuple[str, str | None]:
    """Substitute every `<token>` in `value` from `tokens`.

    Returns `(bound_value, original_value_or_None)` — the second element is
    the pre-substitution string, present only when at least one substitution
    happened (this is exactly what `AcceptanceCriterion.source_template`
    records). Raises `ValueError` naming the supported-token table on any
    token not in `tokens`, and again if a bare `<`/`>` survives binding (a
    malformed token, e.g. `<da te>`, that never matched a known name).
    """
    found = _TOKEN_RE.findall(value)
    if not found:
        return value, None

    unknown = [f"<{tok}>" for tok in found if tok not in tokens]
    if unknown:
        raise ValueError(
            f"{where}: unresolved template token {unknown[0]} — supported tokens are "
            f"{_supported_tokens_table()}. If the value is knowable now, use one of "
            f"those. If it is not knowable until the run exists (e.g. a goal slug an "
            f"attempt will invent), a path check is the wrong predicate here — use a "
            f"command_check the runner can execute, or make this criterion `manual` "
            f"and add a separate executable one beside it."
        )

    bound = _TOKEN_RE.sub(lambda m: tokens[m.group(1)], value)
    if "<" in bound or ">" in bound:
        raise ValueError(
            f"{where}: unresolved template token in {bound!r} — supported tokens are "
            f"{_supported_tokens_table()}."
        )
    return bound, value


# ─────────────────────────────────────────────────────────────────────────────
# Lint — filesystem-dependent, called EXPLICITLY, never from a model validator.
#
# The graph service's synchronous admission-time validation runs
# `CandidateWorkItem` inline (§5.2) on a hosted server that ships only the
# service's own source — there is no working-tree checkout there, so this
# cannot be a model validator (it
# would either error or silently skip on every synchronous admission, and a
# check that behaves differently depending on which process happens to run it
# is worse than an explicit, documented boundary). The graph-machine WORKER's
# node 2 (`validate.py`) re-validates the same candidate with real filesystem
# access via `ctx.deps.evidence_repo`, and is the one caller that should
# invoke this. `evidence_root=None` is the graph-service shape: a clean no-op,
# never a false accept or a false reject.
# ─────────────────────────────────────────────────────────────────────────────


def lint_already_true_file_state(
    criteria: list["AcceptanceCriterion"], *, evidence_root: Path | None
) -> list[str]:
    """Flag `file_state` criteria that are vacuously true/false at filing time.

    `exists` on a path already present, or `not_exists` on a path already
    absent, discharges on an empty attempt and asserts nothing about the work
    — the "already true" half of the T1/T3-shaped defect
    (ExternalReview_GraphMachine_2026-09-04). Returns human-readable findings,
    empty when clean or when `evidence_root` is `None` (best-effort: no root
    to check against is not evidence of anything).
    """
    if evidence_root is None:
        return []
    root = evidence_root.resolve()
    findings: list[str] = []
    for i, crit in enumerate(criteria):
        v = crit.verification
        if not isinstance(v, FileStateCheck) or v.assertion not in ("exists", "not_exists"):
            continue
        candidate_path = (root / v.path).resolve()
        if root not in candidate_path.parents and candidate_path != root:
            continue  # escape is the contract's job (`no_traversal`); not this lint's
        exists_now = candidate_path.exists()
        where = f"acceptance_criteria[{i}]"
        if v.assertion == "exists" and exists_now:
            findings.append(
                f"{where}: `{v.path}` already exists at filing time, so `exists` is true "
                f"before the work starts and discharges on an empty attempt. Assert what "
                f"the work CHANGES instead — `modified_after` (has this path changed since "
                f"filing?) or `hash_equals` (does its content now match a known value?)."
            )
        elif v.assertion == "not_exists" and not exists_now:
            findings.append(
                f"{where}: `{v.path}` is already absent at filing time, so `not_exists` is "
                f"true before the work starts. Assert the removal of something present, or "
                f"point at a path the task actually creates."
            )
    return findings


# ─────────────────────────────────────────────────────────────────────────────
# The proposal
# ─────────────────────────────────────────────────────────────────────────────


class CandidateWorkItem(_StrictArgs):
    """Agent proposal. Independent from the live row-write contract by design."""

    # ── proposed row identity / placement ──────────────────────────────────
    project: str = Field(min_length=1, max_length=255)
    external_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=500)
    type: WorkItemType
    state: WorkItemState | None = None
    parent_work_item: str | None = None
    assignee_agent: str | None = Field(default=None, min_length=1, max_length=100)
    team: list[str] | None = Field(default=None, max_length=50)
    idempotency_key: str = Field(min_length=1, max_length=128)

    # ── required proposal content ──────────────────────────────────────────
    specification: Specification
    source_references: list[SourceReference] = Field(min_length=1, max_length=100)
    effort_level: EffortLevel                       # no None — a proposer must choose
    module: str | None                              # explicit null allowed, omission NOT

    # ── added; no counterpart in WorkItemUpsertArgs ────────────────────────
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1, max_length=20)
    proposer_identity: str = Field(min_length=1, max_length=100)
    proposer_surface: str = Field(min_length=1, max_length=64)
    user_stated_type: str | None = Field(default=None, max_length=100)
    user_stated_action: Literal["add", "update"] | None = None
    source_verbatim: str | None = Field(default=None, max_length=20_000)
    uncertainty_notes: list[Uncertainty] = Field(max_length=10)
    requested_safety_exception: str | None = Field(default=None, max_length=2_000)

    # Change A (Spec_CriteriaUpdate_VerdictReadback_ChiefPM_2026-08-28):
    # `acceptance_criteria` renders on CREATE only — omitted (not null) on
    # UPDATE so a plain state flip never touches it. That default is correct
    # and stays unchanged. What was missing was a door: a criterion filed
    # wrong (e.g. an unresolved `<date>` template token, worklog `307ec44b`)
    # was permanently unfixable, and every UPDATE that DID carry different
    # criteria was silently discarded while the server answered
    # `status: "updated"` (worklog `e1e9b56b`, three independent doors).
    #
    # This flag is the explicit opt-in for the second case. Default `False`
    # preserves the safe behaviour: an UPDATE whose rendered criteria diverge
    # from the stored value is REFUSED loudly (never silently discarded)
    # unless the proposer sets this `True`, in which case the divergence is
    # applied and `acceptance_criteria_ref` is re-pointed at the current run.
    # See `commit.resolve_acceptance_criteria_update`.
    update_acceptance_criteria: bool = False

    # Rule Zero freezes BOTH stated fields. "update this task" states an action as
    # explicitly as it states a type; re-deriving either is the violation, and
    # node 1 is where that is enforced structurally (§5.5.1).
    #
    # `uncertainty_notes` may be EMPTY — an empty list is the explicit "nothing I
    # doubt" answer. It may not be ABSENT: absence is silence, and the two are
    # different answers. Pydantic enforces that automatically because the field
    # has no default.

    @model_validator(mode="after")
    def bind_acceptance_criteria_tokens(self) -> "CandidateWorkItem":
        """The binder (ExternalReview_GraphMachine_2026-09-04). Runs on EVERY
        `CandidateWorkItem` construction, everywhere one is built — the graph service's
        synchronous admission, the worker's node 2 re-validation, `taskgraph_emit.py`,
        the corpus harness — because it lives in `__init__`'s own validation path
        rather than depending on any one caller to invoke it. Idempotent: a
        candidate re-parsed after its tokens are already resolved has nothing
        left to bind (concrete values are never token-shaped), so re-running
        this on the worker's re-validation is a safe no-op, not a second bite.
        """
        filing_date = date.today()
        path_tokens = _filing_tokens(
            project=self.project, external_id=self.external_id,
            idempotency_key=self.idempotency_key, filing_date=filing_date, path_mode=True,
        )
        text_tokens = _filing_tokens(
            project=self.project, external_id=self.external_id,
            idempotency_key=self.idempotency_key, filing_date=filing_date, path_mode=False,
        )

        # `source_template` is SYSTEM-OWNED (see the field's docstring): every
        # criterion is reconstructed below with a freshly computed value —
        # `None` unless THIS pass detects a real substitution — so a proposer
        # cannot forge the audit trail by sending the field directly.
        bound_criteria: list[AcceptanceCriterion] = []
        for i, crit in enumerate(self.acceptance_criteria):
            v = crit.verification
            template: dict[str, str] | None = None

            if isinstance(v, FileStateCheck):
                new_path, path_template = _bind_token_string(
                    v.path, path_tokens, where=f"acceptance_criteria[{i}].verification.path"
                )
                new_expected, expected_template = (
                    _bind_token_string(
                        v.expected, text_tokens,
                        where=f"acceptance_criteria[{i}].verification.expected",
                    )
                    if v.expected is not None else (v.expected, None)
                )

                # `modified_after` names "changed since filing" — if the
                # proposer left no reference timestamp, the filing instant
                # itself IS the reference. Auto-filled here (not via a named
                # token) because it needs sub-day precision `<date>`
                # deliberately does not carry, and it is a default-fill, not
                # a template resolution — it does not enter `source_template`.
                if v.assertion == "modified_after" and not new_expected:
                    new_expected = datetime.now(timezone.utc).isoformat()

                if new_path != v.path or new_expected != v.expected:
                    # Re-construct through `__init__` (not `model_copy`) so
                    # field validators — `no_traversal` in particular —
                    # re-run on the BOUND value. A token substitution should
                    # never be able to introduce a traversal the original
                    # template didn't already contain, but this is the cheap
                    # belt-and-braces check rather than an assumption.
                    v = FileStateCheck(
                        **{**v.model_dump(), "path": new_path, "expected": new_expected}
                    )

                t: dict[str, str] = {}
                if path_template is not None:
                    t["path"] = path_template
                if expected_template is not None:
                    t["expected"] = expected_template
                template = t or None

            bound_criteria.append(
                AcceptanceCriterion(statement=crit.statement, verification=v, source_template=template)
            )

        self.acceptance_criteria = bound_criteria
        return self

    @model_validator(mode="after")
    def at_least_one_executable_criterion(self) -> "CandidateWorkItem":
        """Weak criteria are how a trivial attempt mints false credit.

        At least one criterion must be dischargeable by machine, or nothing
        downstream can distinguish `done` from `asserted done`.

        This is NOT a ban on `manual`. Visual and judgment work keeps its manual
        criteria — it just has to name one executable check alongside them
        ("renders with no console errors" beside "looks right"). If a proposer
        cannot name a single machine-checkable condition for work it is
        proposing, the criteria are not yet good enough to attempt against.
        """
        if all(c.verification.kind == "manual" for c in self.acceptance_criteria):
            raise ValueError(
                "acceptance_criteria: at least one criterion must use a non-manual "
                "verification kind. All-manual criteria cannot be discharged by node 6 "
                "and therefore cannot support a completion claim. Keep the manual "
                "criteria and ADD an executable one — 'renders with no console errors' "
                "beside 'looks right'"
            )
        return self

    # ── on `module`, and why there is no validator for it ──────────────────
    #
    # `module: str | None` is declared with NO DEFAULT, which makes it required
    # while still accepting an explicit null. That is exactly §6.1's
    # "explicit null allowed, omission not", enforced by the type system rather
    # than by a check.
    #
    # An `mode="after"` validator inspecting `model_fields_set` was written here
    # first and deleted: field validation runs before it, so pydantic raises on
    # the missing field and the validator is unreachable. Verified under both
    # pins — the emitted error is `loc=('module',), type='missing'`, which is
    # what `validator-omitted-module-rejected` asserts on.
    #
    # The distinction the field encodes is worth restating for whoever reads a
    # rejection: an explicit null is a proposer saying "this belongs to no
    # module"; an omission is a proposer who never considered the question. The
    # graph can act on the first and must refuse the second. A proposer that
    # repairs the rejection by sending null when it actually had a module in mind
    # has laundered a placement bug through a validation message.
