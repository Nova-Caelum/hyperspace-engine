# Vendored from the Nova Caelum graph_library contracts/results.py, 2026-09-26.
# Adapted for hyperspace-engine; see THIRD_PARTY_NOTICES.md.
"""Verifier outputs — `CriterionVerdict`, `VerificationResult` (§7).

Only the two verdict types the verifier returns are vendored; the attempter's
`AttemptResult` and the adjudication graph's `RouteDecision` are deferred with it.

The one idea these three encode, stated once: **an attempt produces a CLAIM, a
verification produces a VERDICT, and only a verdict can support a route.**

§9 node 5 says the attempter "never does" treat its result as anything but a
claim. That is enforced here by giving `AttemptResult` no field that could be
read as proof, and by making `VerificationResult` refuse to pass with nothing
discharged.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from .candidate import _StrictArgs


class CriterionVerdict(_StrictArgs):
    """One criterion, one verdict, one piece of evidence.

    §14.2 requires "100% criterion-level evidence for every acceptance." An
    acceptance with no `evidence` string is refused below, so that requirement is
    a property of the type rather than an instruction to the verifier.
    """

    statement: str = Field(min_length=1, max_length=2_000)
    verification_kind: str
    discharged: bool
    evidence: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def discharged_requires_evidence(self) -> "CriterionVerdict":
        if self.discharged and not (self.evidence or "").strip():
            raise ValueError(
                "a discharged criterion must carry the evidence that discharged it"
            )
        # §9 node 6: "a `manual` criterion is left explicitly UNDISCHARGED and
        # passed to node 7 / the human — never assumed satisfied."
        if self.verification_kind == "manual" and self.discharged:
            raise ValueError(
                "a manual criterion cannot be discharged by node 6; it is passed on "
                "explicitly undischarged"
            )
        return self


class VerificationResult(_StrictArgs):
    """A verdict. Only a verdict can support a route.

    Node 6 (deterministic) and node 7 (semantic) both return this shape, but they
    are gated differently and the corpus keeps them apart: node 6 is a 100% gate,
    node 7 a percentage gate (L8). `consulted_transcript` exists so node 6's
    boundary is auditable rather than assumed — a verdict that would change if
    the transcript were removed is a verdict the transcript produced.
    """

    passed: bool
    verdicts: list[CriterionVerdict] = Field(default_factory=list)
    consulted_transcript: bool = False
    notes: str | None = Field(default=None, max_length=20_000)

    @property
    def discharged_count(self) -> int:
        return sum(1 for v in self.verdicts if v.discharged)

    @model_validator(mode="after")
    def pass_requires_a_discharged_predicate(self) -> "VerificationResult":
        """§9 node 6, verbatim: "a pass here requires at least one registered
        deterministic predicate to have actually run and returned true — zero
        discharged predicates is not a pass, it is `failed_uncertain`."

        This is T8's mechanism. Vacuous truth is the most dangerous pass a
        verification suite can produce, because it is indistinguishable from a
        real one at every surface except this check.
        """
        if self.passed and not any(v.discharged for v in self.verdicts):
            raise ValueError(
                "verification cannot pass with zero discharged predicates; that is "
                "failed_uncertain, not a pass"
            )
        return self
