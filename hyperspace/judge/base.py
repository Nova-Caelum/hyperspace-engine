"""The `Judge` interface — what the verification graph's two semantic steps call.

Two calls, disjoint inputs (the canonical verifier's handoff D10):
  * `judge_criteria` — step 3: are the criteria about THIS task and observable?
    Sees the task statement and the criteria. Never the world.
  * `judge_evidence` — step 2: does the observed delta establish each criterion,
    and is the task's stated outcome realized? Sees the task statement, the
    criteria and rendered observations. Never an account of the work.

Each returns the typed judgment plus the usage record the canonical judges
return (`model`, `input_tokens`, `output_tokens`, `requests`). The runners that
fill this interface (`openrouter`, `anthropic`, `claude-code`, `codex`) belong to
the judge row; this row ships the interface and `none` only.

A runner that cannot run raises `JudgeUnavailable`. The graph treats it like any
judge error: one retry, then `uncertain` — never `done`.
"""
from typing import Protocol, runtime_checkable

from ..contracts.candidate import AcceptanceCriterion
from .judgments import CriteriaJudgment, Judgment


@runtime_checkable
class Judge(Protocol):
    name: str

    async def judge_criteria(
        self, task: str, criteria: list[AcceptanceCriterion]
    ) -> tuple[CriteriaJudgment, dict]: ...

    async def judge_evidence(
        self, task: str, criteria: list[AcceptanceCriterion], observations: list[str]
    ) -> tuple[Judgment, dict]: ...


class JudgeUnavailable(Exception):
    """The configured runner cannot judge right now (no key, no CLI, no network)."""

    def __init__(self, runner: str, reason: str) -> None:
        super().__init__(f"judge {runner!r} unavailable: {reason}")
        self.runner = runner
        self.reason = reason
