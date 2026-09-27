"""`NoneJudge` — the keyless runner. It does not judge, and it does not pretend to.

Both calls return `uncertain=True` with nothing accepted and a reason naming
that no judge is configured. The verification graph never relies on those
answers: when `Deps.judge_name == "none"` its `CriteriaQuality` and
`EvidenceJudge` nodes record `skipped` without calling the judge at all, and a
row closes `done` only when the deterministic landing check discharged every
criterion. These methods exist so a caller that invokes the interface directly
gets an honest non-answer rather than a fabricated pass.
"""
from ..contracts.candidate import AcceptanceCriterion
from .judgments import CriteriaJudgment, CriterionJudgment, CriterionQuality, Judgment

REASON = "no judge is configured (judge = \"none\"); nothing was judged"
_USAGE = {"model": None, "input_tokens": 0, "output_tokens": 0, "requests": 0}


class NoneJudge:
    name = "none"

    async def judge_criteria(
        self, task: str, criteria: list[AcceptanceCriterion]
    ) -> tuple[CriteriaJudgment, dict]:
        return CriteriaJudgment(
            acceptable=False, uncertain=True, reason=REASON,
            criteria=[CriterionQuality(statement=c.statement, relevant=False, assessable=False, reason=REASON)
                      for c in criteria],
        ), dict(_USAGE)

    async def judge_evidence(
        self, task: str, criteria: list[AcceptanceCriterion], observations: list[str]
    ) -> tuple[Judgment, dict]:
        return Judgment(
            accepted=False, outcome_realized=False, uncertain=True, reason=REASON,
            criteria=[CriterionJudgment(statement=c.statement, discharged=False, evidence=REASON)
                      for c in criteria],
        ), dict(_USAGE)
