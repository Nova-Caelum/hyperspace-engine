# Vendored from the Nova Caelum graph_library contracts, 2026-09-26.
# Adapted for the hyperspace-engine plugin; see bin/PORT_NOTES.md.
"""Closed value sets for the Graph Machine.

Transcribed from the PRD's own typed contracts. Where the PRD's prose and its
typed contracts disagree, **the typed contract wins** and the divergence is
recorded in a comment rather than resolved by preference — §9 node 8 describes
five dispositions in prose while §6.2 and §6.4 both carry a six-value `Literal`,
and the missing sixth is load-bearing.

Import-portability: this module imports nothing outside `typing` and must remain
that way. §3.2 requires the contract package to import cleanly under
`pydantic==2.10.3` **with no `pydantic-graph` installed**, because the graph
service imports it at that pin to validate agent ingress inline (§5.2).
"""

from __future__ import annotations

from typing import Literal

# ─────────────────────────────────────────────────────────────────────────────
# Safety class — L7's three-tier side-effect taxonomy (§11).
# ─────────────────────────────────────────────────────────────────────────────

SafetyClass = Literal[
    "sandboxed",           # tier 1 — contained in a worktree; discard is complete
    "receipt_reversible",  # tier 2 — reaches a real external system; reversible via receipt
    "never_attempt",       # tier 3 — neither containable nor reversible
]

SAFETY_TIER: dict[str, int] = {
    "sandboxed": 1,
    "receipt_reversible": 2,
    "never_attempt": 3,
}

# ─────────────────────────────────────────────────────────────────────────────
# Change kind — §10, one member per routing-table row.
# ─────────────────────────────────────────────────────────────────────────────

ChangeKind = Literal[
    "code_infra",
    "ui_frontend",
    "doc_sync_wiki",
    "n8n_workflow",
    "repo_verification_deploy",
    "taskgraph_mutation",
    "irreversible_schema_external",
    "ambiguous",
]

# L5 — the attempter roster is CLOSED. Orchestration and grand-orchestration
# personas never appear: work qualifying for auto-attempt is execution work by
# definition, and a task genuinely needing orchestration judgment fails the
# quick-and-safe test and should file.
AttempterPersona = Literal[
    "engineer",
    "designer",
    "librarian",
    "automator",
    "devops-local",
]

# §10, transcribed row for row. `persona: None` means the row has no executor —
# for `taskgraph_mutation` because the change IS the row, for
# `irreversible_schema_external` because L7 forbids the attempt, and for
# `ambiguous` because the semantic fallback must resolve a kind and RE-ENTER
# this table rather than naming a persona itself.
CHANGE_KIND_ROUTING: dict[str, dict[str, object]] = {
    "code_infra": {"persona": "engineer", "safety_class": "sandboxed"},
    "ui_frontend": {"persona": "designer", "safety_class": "sandboxed"},
    "doc_sync_wiki": {"persona": "librarian", "safety_class": "sandboxed"},
    "n8n_workflow": {"persona": "automator", "safety_class": "receipt_reversible"},
    "repo_verification_deploy": {
        "persona": "devops-local",
        "safety_class": "receipt_reversible",
    },
    "taskgraph_mutation": {"persona": None, "safety_class": "sandboxed"},
    "irreversible_schema_external": {"persona": None, "safety_class": "never_attempt"},
    "ambiguous": {"persona": None, "safety_class": None},
}

# ─────────────────────────────────────────────────────────────────────────────
# Terminal route — §6.2 `MachineItem.final_route`, §6.4 `OutcomeNotice`.
# ─────────────────────────────────────────────────────────────────────────────

TerminalRoute = Literal[
    "filed",
    "completed_without_filing",
    "dissolved_on_contact",
    "rejected_invalid",
    "escalated_protected",
    "failed_uncertain",
]

# `dissolved_on_contact` vs `completed_without_filing` — the split a reader will
# collapse if nobody stops them, and §6.2 states what collapsing it costs:
#
#   "Without this split the corpus verdict at §14.3 for PDC-04 (fabricated
#    mismatch) is unrecordable, and the fabrication signal is written and then
#    immediately erased — a hollow item and a genuine 30-second fix become the
#    same row. This value is the only reason per-proposer hollow rate exists."
#
# Real work really done            -> completed_without_filing
# The premise was false and the attempt proved it -> dissolved_on_contact

# ─────────────────────────────────────────────────────────────────────────────
# Run status — §6.2 / §6.5. One writer per status; see §6.5's node mapping.
# ─────────────────────────────────────────────────────────────────────────────

RunStatus = Literal[
    # transient, in node order (classify BEFORE retrieve — settled in §6.5)
    "queued",                       # the graph service at admission, NOT node 1
    "claimed",                      # node 1
    "validating",                   # node 2
    "classifying",                  # node 3
    "retrieving_context",           # node 4
    "attempting",                   # node 5
    "deterministic_verification",   # node 6
    "semantic_verification",        # node 7
    "crediting",                    # node 8 branch
    "filing",                       # node 8 branch
    "escalating",                   # node 8 branch
    # terminal — all written by node 9, the one node every path reaches
    "completed",
    "rejected_invalid",
    "failed_uncertain",
    "input_required",
    "cancelled",
    "failed_internal",
    "attempt_skipped_no_local_runtime",
]

TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        "completed",
        "rejected_invalid",
        "failed_uncertain",
        "input_required",
        "cancelled",
        "failed_internal",
        "attempt_skipped_no_local_runtime",
    }
)

# §13.3, verbatim: "the fallback fires on any terminal state that is not a
# legitimate outcome. Cause is recorded; cause does not gate."
#
# A chain BUG that crashes a run and is only logged is silent non-filing reached
# by a different road, and the forbidden outcome does not care why it happened.
# That is why `failed_internal` is absent from this set and `failed_uncertain`
# is too — both fire.
LEGITIMATE_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"completed", "rejected_invalid", "cancelled"}
)


def fallback_should_fire(status: str) -> bool:
    """The §13.3 trigger predicate. Deterministic, total, and cause-blind.

    System code calls this. **No candidate field reaches it and no model can
    request it** — that is L14 extended to the failure path, and it is what stops
    "the chain failed, so I'll write directly" from becoming the universal bypass
    on the first bad day.
    """
    if status not in TERMINAL_STATUSES:
        return False
    return status not in LEGITIMATE_TERMINAL_STATUSES


# ─────────────────────────────────────────────────────────────────────────────
# Run grade — §6.2 / §6.4. Terminal `OutcomeNotice` only.
# ─────────────────────────────────────────────────────────────────────────────

RunGrade = Literal["success", "fallback_completed", "true_failure"]

# §13.3's two failure domains, and why an alert must distinguish them:
#   fallback_completed — the local chain died, the graph is still writable, the
#                        item was filed unverified and the user was pinged.
#   true_failure       — the graph service itself is down. NOTHING was filed, no write
#                        was attempted, and the work exists only in a JSON file.
# "An alert that does not distinguish them is a defect" — they demand different
# actions from a human at 3am.

# ─────────────────────────────────────────────────────────────────────────────
# Verification predicate kinds — §6.1. The allowlist IS the security boundary.
# ─────────────────────────────────────────────────────────────────────────────

VerificationKind = Literal[
    "command_check",
    "file_state",
    "db_readback",
    "http_readback",
    "manual",
]

# §6.1: the proposer SELECTS a typed check; it does not supply code for the
# verifier to execute. These closed sets are the entire defence, and they only
# work because no proposer string is ever interpolated into a command line, a
# SQL statement, or a URL.
CommandCheckId = Literal["tests", "typecheck", "build", "lint", "git_diff_nonempty"]

FileStateAssertion = Literal[
    "exists", "not_exists", "contains", "hash_equals", "modified_after", "glob_exists",
]
# `modified_after` and `glob_exists` (ExternalReview_GraphMachine_2026-09-04) close
# the vocabulary gap `exists`-on-an-already-existing-path was being misused for: an
# author who means "this file CHANGED" had no word for it. `modified_after` compares
# a path's last-touched time (git log preferred, mtime fallback) against a reference
# timestamp bound at filing time; `glob_exists` matches a pattern instead of a literal
# path, for outputs whose exact name is only known once the run exists.

UncertaintyKind = Literal[
    "already-done",      # may already be complete; check before attempting
    "duplicate",         # a row for this may already exist
    "wrong-type",        # task vs module vs project genuinely unclear
    "wrong-scope",       # boundary of the work is not certain
    "missing-context",   # retrieval could not reach something load-bearing
    "unverified-claim",  # a stated fact in the specification is not evidenced
]

# ─────────────────────────────────────────────────────────────────────────────
# Live Task Graph vocabulary — mirrors of the SERVER's enums, not choices here.
# `work_graph_contracts.py` is the source of truth; these are enforcing mirrors,
# and the parity test in the corpus is what keeps them honest.
# ─────────────────────────────────────────────────────────────────────────────

WorkItemType = Literal[
    "task", "draft", "audit", "investigation", "design",
    "build", "decision", "phase", "workstream",
]

WorkItemState = Literal[
    "pending-review", "ready", "in-progress", "blocked", "done", "deferred", "archived",
]

# "unknown" is distinct from None: None means the field was never filled in;
# "unknown" is a deliberate assertion that no good estimate exists yet.
# `CandidateWorkItem` forbids the None — a proposer must choose, including
# choosing "unknown".
EffortLevel = Literal["quick", "medium", "hard", "max", "unknown"]


# ─────────────────────────────────────────────────────────────────────────────
# Terminal-completion predicate — ADR D1 CORRECTION (2026-09-04).
# ─────────────────────────────────────────────────────────────────────────────
#
# D1 split the write path on CREATE-vs-UPDATE and sent every UPDATE down the
# synchronous door on the premise that "there is nothing to adjudicate about a
# `done` flip." That premise was half right and the missing half cost a night:
# there is nothing to ADJUDICATE, but there is everything to VERIFY, and those
# are different operations. Verification needs a real checkout of the world the
# criteria point at; the synchronous door ran on a hosted server, which had a
# checkout of the graph service's own source tree and nothing else. So `done` was
# refused for every criterion naming a path in the user's working tree — i.e. for
# all real work.
#
# The corrected split is TERMINAL-vs-not:
#
#   state == "done"  -> the async chain, where node 6 runs against the working tree
#   everything else  -> the fast synchronous door, unchanged
#   CREATE           -> unchanged, adjudicated
#
# This predicate is the one place that split is expressed, so the three nodes
# that must agree about it (classify: do not attempt finished work; node 6: a
# zero-discharge done flip is a failure, not a pass-through; node 8: verify
# before flipping, and flip with a MINIMAL request) cannot drift apart.
#
# Duck-typed on purpose: `enums.py` imports nothing outside `typing` (§3.2
# import-portability, stated at the top of this file), so it cannot name
# `CandidateWorkItem` without breaking the graph service's own inline-validation import.


def is_done_flip(candidate: object) -> bool:
    """True when this candidate asserts terminal completion (`state == "done"`).

    Read it as "this write claims work is finished," not as "this is an
    UPDATE" — a CREATE carrying `state="done"` is the same claim and gets the
    same treatment. The server decides the ROUTE (async chain vs sync door);
    the chain uses this to decide BEHAVIOUR once a run is already in flight.
    """
    return getattr(candidate, "state", None) == "done"


# ─────────────────────────────────────────────────────────────────────────────
# Registration-vs-completion predicate — ADR D1 EXTENSION (2026-09-04).
# ─────────────────────────────────────────────────────────────────────────────
#
# THE DEFECT THIS CLOSES: an agent could not file a task it had not already
# done. Node 2 rejects a candidate whose criteria are ALREADY TRUE; node 6
# rejected one whose criteria are NOT YET TRUE. A genuinely forward-looking
# task satisfied neither, so it never reached node 8 and no row was filed —
# and the only new rows the chain would accept were ones whose criteria
# already held, i.e. the hollow rows this machine exists to prevent. Live
# evidence: run 2eec589f (`ncf-m4-exit-gate-completion`, `state="blocked"`),
# plus ~15 identical `failed_uncertain` CREATEs that read as noise for a week.
#
# D1's correction drew the completion-vs-everything-else split at UPDATE. This
# is the SAME split, drawn at CREATE, where it was missing:
#
#   a COMPLETION CLAIM   -> zero discharged predicates is the unsupported
#                           claim node 6 exists to refuse (T8).
#   a REGISTRATION       -> zero discharged predicates is the EXPECTED state
#                           of work that has not been done. Refusing it is
#                           refusing to track real work.
#
# Node 6's zero-discharge rule and the corpus harness's scripted stand-in for
# it (`corpus/harness/primitives_exec.py`) both call THIS function, because
# two copies of this rule already drifted once: the harness copy never grew
# D1's `is_done_flip` clause, so the corpus would have kept passing while
# production behaviour moved underneath it — a component passing while the
# integration it exists for silently fails is this project's named disease.
#
# Duck-typed for the same reason `is_done_flip` is: this module imports
# nothing outside `typing` (§3.2 import-portability) and cannot name
# `CandidateWorkItem` or `AttemptResult` without breaking the graph service's
# inline validation import.


def claims_completion(candidate: object, attempt: object) -> bool:
    """True when this run ASSERTS that work is finished, by either route.

    Two independent assertions, and both must be caught, because they arrive
    on different objects:

    * the CANDIDATE says so — `state="done"`. The claim is the run's INPUT and
      node 3 marks it not-attempt-eligible, so the attempt beside it is a
      synthetic `claims_complete=False` placeholder that would mask the claim
      if this read the attempt alone.
    * the ATTEMPT says so — `AttemptResult.claims_complete`. Reading that ONE
      BOOLEAN is not a breach of node 6's transcript boundary: the boundary
      forbids the verifier taking the attempt's NARRATIVE as evidence, and
      this flag is not evidence — it selects which question is being asked.
      `verify()` still has no parameter for the transcript, which is where
      that boundary is made structural.

    `attempt is None` reads as no claim, which is correct for every caller
    that runs before node 5.
    """
    return is_done_flip(candidate) or bool(getattr(attempt, "claims_complete", False))
