"""`PydanticAIJudge` — the two keyed runners, `openrouter` and `anthropic`.

Agent construction mirrors the canonical judges' shared runtime module — one
model string, one prompt file as the system instructions, retries on output
validation, temperature 0 for a stable verdict — MINUS its unconditional
key-fetch helper and secret-store fallback (register A4: those do not come
across). This runner reads the provider's key from the environment only and
raises `JudgeUnavailable` if it is absent, before any `Agent` touches a model.

`model_override` (tests only) substitutes a pydantic-ai test model — verified
via context7 `/pydantic/pydantic-ai`, 2026-09-26:
  * `pydantic_ai.models.test.TestModel(custom_output_args: Any | None = None,
    ...)` — when set, "these args will be passed to the output tool", i.e. the
    exact dict is validated straight into the agent's structured `output_type`,
    bypassing TestModel's own (validator-unaware) schema-seed generation.
  * `Agent.run(user_prompt, *, model: Model | KnownModelName | str | None =
    None, ...)` accepts a per-call model override directly — confirmed by the
    docs' own `tools.md` example: `result = agent.run_sync('hello',
    model=test_model)`. Used here instead of construction-time replacement so
    the Agent is always built against the real provider string and the
    override is purely a call-time swap.
"""
from __future__ import annotations

import os
from typing import Any

from pydantic_ai import Agent

from ..config import DEFAULT_MODELS
from ..contracts.candidate import AcceptanceCriterion
from ._prompts import build_criteria_prompt, build_evidence_prompt, load_prompt
from .base import JudgeUnavailable
from .judgments import CriteriaJudgment, Judgment

_ENV_VARS = {"openrouter": "OPENROUTER_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}

# Matches the canonical judges' `output_retries` — a judge call is one request
# on a well-behaved model, a few more on a schema-flaky one.
_OUTPUT_RETRIES = 4


def _usage_dict(model_label: str, result: Any) -> dict:
    usage = result.usage
    if callable(usage):  # tolerate either shape across pydantic-ai minors
        usage = usage()
    return {
        "model": model_label,
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "requests": getattr(usage, "requests", None),
    }


class PydanticAIJudge:
    """`provider` in {"openrouter", "anthropic"}."""

    def __init__(self, provider: str, model: str | None = None, *, model_override: Any = None) -> None:
        if provider not in _ENV_VARS:
            raise ValueError(f"unknown provider {provider!r} — must be one of: openrouter, anthropic")
        env_var = _ENV_VARS[provider]
        if not os.environ.get(env_var):
            # Raised here, at construction — before any Agent is built and
            # before `model_override` (if any) is even consulted, so this
            # fires identically whether or not a fake model is in play.
            raise JudgeUnavailable(provider, f"{env_var} is not set in the environment")

        self.name = provider
        self._model_override = model_override
        self.model_id = model or DEFAULT_MODELS[provider]
        model_string = f"{provider}:{self.model_id}"

        self._criteria_agent = Agent(
            model_string,
            output_type=CriteriaJudgment,
            instructions=load_prompt("criteria_judge"),
            retries={"tools": 0, "output": _OUTPUT_RETRIES},
            model_settings={"temperature": 0.0},
        )
        self._evidence_agent = Agent(
            model_string,
            output_type=Judgment,
            instructions=load_prompt("evidence_judge"),
            retries={"tools": 0, "output": _OUTPUT_RETRIES},
            model_settings={"temperature": 0.0},
        )

    def _usage_label(self) -> str:
        return f"{self.name}:{self.model_id}"

    async def judge_criteria(
        self, task: str, criteria: list[AcceptanceCriterion]
    ) -> tuple[CriteriaJudgment, dict]:
        prompt = build_criteria_prompt(task, criteria)
        kwargs = {"model": self._model_override} if self._model_override is not None else {}
        result = await self._criteria_agent.run(prompt, **kwargs)
        return result.output, _usage_dict(self._usage_label(), result)

    async def judge_evidence(
        self, task: str, criteria: list[AcceptanceCriterion], observations: list[str]
    ) -> tuple[Judgment, dict]:
        prompt = build_evidence_prompt(task, criteria, observations)
        kwargs = {"model": self._model_override} if self._model_override is not None else {}
        result = await self._evidence_agent.run(prompt, **kwargs)
        return result.output, _usage_dict(self._usage_label(), result)
