"""Judge runners for the verification graph. This package ships the `Judge`
interface, the judgment models, and the five runners: `none` (keyless),
`openrouter` / `anthropic` (keyed, via pydantic-ai), and `claude-code` /
`codex` (CLI subprocess)."""
from ..config import Config
from .base import Judge, JudgeUnavailable
from .cli_runner import CliJudge
from .judgments import CriteriaJudgment, CriterionJudgment, CriterionQuality, Judgment
from .none_runner import NoneJudge
from .pydantic_ai_runner import PydanticAIJudge

__all__ = [
    "CliJudge", "CriteriaJudgment", "CriterionJudgment", "CriterionQuality",
    "Judge", "JudgeUnavailable", "Judgment", "NoneJudge", "PydanticAIJudge",
    "get_judge",
]


def get_judge(config: Config) -> Judge:
    """Maps `config.judge` (one of `hyperspace.config.JUDGES`) to a runner
    instance. Raises the same `JudgeUnavailable` a keyed runner would raise
    on a missing key — `get_judge` does not swallow it; the caller (the
    setup skill's probe, or a test) decides what to do with an unavailable
    runner."""
    if config.judge == "none":
        return NoneJudge()
    if config.judge in ("openrouter", "anthropic"):
        return PydanticAIJudge(config.judge, model=config.model)
    if config.judge in ("claude-code", "codex"):
        return CliJudge(config.judge, model=config.model)
    raise ValueError(
        f"unknown judge {config.judge!r} — must be one of: openrouter, anthropic, claude-code, codex, none"
    )
