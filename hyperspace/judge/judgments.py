# Vendored from the Nova Caelum graph_library primitives/judges/judgments.py, 2026-09-26.
# Adapted for hyperspace-engine; see THIRD_PARTY_NOTICES.md.
"""Typed judgment contracts for the two verifier judges.

The point of this file: every property a judge must have is enforced HERE as a
schema invariant, not asked for in a prompt. A judgment that accepts an uncited
criterion, or accepts while the outcome is not realized, is not "downgraded" — it
is unconstructible, and pydantic-ai hands the validator's own message back to
the model as a retry. Same move as `contracts/results.py`'s
`pass_requires_a_discharged_predicate`.

Two judges, two contracts, disjoint inputs (handoff D10):
  * `CriteriaJudgment` — step 3: are the criteria about THIS task and observable?
    Sees the task statement and the criteria. Never the world.
  * `Judgment` — step 2: does the observed delta establish each criterion, and is
    the task's stated outcome realized? Sees the task statement, the criteria
    step 3 accepted, and the observed delta. Never an account of the work.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — the evidence judge
# ─────────────────────────────────────────────────────────────────────────────


class CriterionJudgment(BaseModel):
    """One criterion, judged against the observed world."""

    statement: str = Field(description="the acceptance criterion, restated verbatim")
    discharged: bool = Field(description="does the observed evidence establish it")
    evidence: str = Field(
        default="",
        description=(
            "the SPECIFIC observation that settles it — a quoted line with its "
            "file and location. Required whenever discharged is true."
        ),
    )

    @model_validator(mode="after")
    def discharged_requires_cited_evidence(self) -> "CriterionJudgment":
        # The message below is what the model is told on retry — so it must be
        # an instruction, not a complaint.
        if self.discharged and not self.evidence.strip():
            raise ValueError(
                f"criterion {self.statement!r} is marked discharged with no cited "
                "evidence. Quote the specific observation that settles it — a line "
                "with its file and location. If you cannot point at one, the "
                "criterion is NOT discharged; set discharged=false."
            )
        return self


class Judgment(BaseModel):
    """The evidence judge's verdict. `uncertain` is a first-class outcome."""

    accepted: bool = Field(
        description="true only if EVERY criterion is discharged AND outcome_realized is true"
    )
    outcome_realized: bool = Field(
        description=(
            "is the task's stated outcome now true in the world because of the "
            "observed change — the thing itself, not a representation of it"
        )
    )
    criteria: list[CriterionJudgment] = Field(
        min_length=1, description="one entry per criterion supplied, in order"
    )
    reason: str = Field(description="one sentence")
    uncertain: bool = Field(
        default=False,
        description=(
            "true when the evidence supplied is insufficient to decide — distinct "
            "from a confident rejection. Never guess to avoid this."
        ),
    )

    @model_validator(mode="after")
    def acceptance_requires_every_criterion_and_the_outcome(self) -> "Judgment":
        if self.accepted:
            undischarged = [c.statement for c in self.criteria if not c.discharged]
            if undischarged:
                raise ValueError(
                    "accepted=true but these criteria are not discharged: "
                    f"{undischarged!r}. Acceptance requires ALL criteria discharged. "
                    "Either discharge them with cited evidence or set accepted=false."
                )
            if not self.outcome_realized:
                raise ValueError(
                    "accepted=true but outcome_realized=false. If the task's stated "
                    "outcome is not realized in the world, set accepted=false."
                )
            if self.uncertain:
                raise ValueError(
                    "accepted=true and uncertain=true are contradictory. If the "
                    "evidence was sufficient to accept, it was not uncertain."
                )
        return self


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — the criteria-quality judge
# ─────────────────────────────────────────────────────────────────────────────


class CriterionQuality(BaseModel):
    """One criterion, judged for relevance and assessability — no world seen."""

    statement: str = Field(description="the acceptance criterion, restated verbatim")
    relevant: bool = Field(
        description="observing this true would be evidence THIS task's work was done"
    )
    assessable: bool = Field(
        description="someone could go to a named place and observe yes/no"
    )
    reason: str = Field(description="one sentence")


class CriteriaJudgment(BaseModel):
    """Step 3's verdict on the criteria themselves."""

    acceptable: bool = Field(
        description="true only if every criterion is relevant AND every criterion is assessable"
    )
    criteria: list[CriterionQuality] = Field(
        min_length=1, description="one entry per criterion supplied, in order"
    )
    reason: str = Field(description="one sentence")
    uncertain: bool = Field(
        default=False,
        description="true only when the task statement is too thin to judge relevance",
    )

    @model_validator(mode="after")
    def acceptable_requires_every_criterion(self) -> "CriteriaJudgment":
        if self.acceptable:
            bad = [
                c.statement for c in self.criteria if not (c.relevant and c.assessable)
            ]
            if bad:
                raise ValueError(
                    "acceptable=true but these criteria are not both relevant and "
                    f"assessable: {bad!r}. Either mark each relevant and assessable "
                    "with a reason, or set acceptable=false."
                )
            if self.uncertain:
                raise ValueError(
                    "acceptable=true and uncertain=true are contradictory."
                )
        return self
