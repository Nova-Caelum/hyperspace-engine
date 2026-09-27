# Message construction ported from the Nova Caelum graph_library
# primitives/judges/{criteria_agent,semantics_agent}.py, 2026-09-26 — the
# rendering only (not the key loading or agent wiring; register A4). Shared by
# `pydantic_ai_runner` and `cli_runner` so every runner sends the same prompt
# text and produces judgments comparable to the canonical judges'.
"""Shared prompt-file loading and message construction for the semantic judge
runners. The prompt files (`hyperspace/verify/prompts/*.md`) are the system
instructions; the functions here render the per-call user message (task,
criteria, and — for the evidence judge — observations)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "verify" / "prompts"


def load_prompt(name: str) -> str:
    """The prompt IS the file — no inline copy anywhere (mirrors the
    canonical `_runtime.py`'s own rule)."""
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def _criterion_statement(c: Any) -> str:
    return getattr(c, "statement", None) or (c.get("statement", str(c)) if isinstance(c, dict) else str(c))


def _describe_criterion(c: Any) -> str:
    """One line: the criterion's statement plus what specifically checks it —
    ported verbatim from the canonical criteria judge's `_describe`."""
    v = getattr(c, "verification", None)
    if v is None and isinstance(c, dict):
        v = c.get("verification")
    kind = getattr(v, "kind", None) or (v.get("kind") if isinstance(v, dict) else "?")
    detail = ""
    if kind == "file_state":
        path = getattr(v, "path", None) or v.get("path")
        assertion = getattr(v, "assertion", None) or v.get("assertion")
        expected = getattr(v, "expected", None) or (v.get("expected") if isinstance(v, dict) else None)
        if assertion == "contains":
            detail = f" — checked by: the file `{path}` contains the text `{expected}`"
        elif assertion == "exists":
            detail = f" — checked by: the file `{path}` exists"
        elif assertion == "not_exists":
            detail = f" — checked by: the file `{path}` does not exist"
        elif assertion == "glob_exists":
            detail = f" — checked by: some file matches the pattern `{path}`"
        elif assertion == "modified_after":
            detail = f" — checked by: `{path}` was modified after {expected}"
        elif assertion == "hash_equals":
            detail = f" — checked by: `{path}`'s content hash equals a known value"
        else:
            detail = f" — checked by: file_state {assertion} on `{path}`"
    elif kind == "command_check":
        cid = getattr(v, "check_id", None) or v.get("check_id")
        detail = f" — checked by running the registered command `{cid}` and reading its exit status"
    elif kind == "manual":
        instruction = getattr(v, "instruction", None) or (v.get("instruction") if isinstance(v, dict) else "")
        detail = f" — manual check; instruction to the human: {instruction}"
    else:
        detail = f" — {kind}"
    return f"{_criterion_statement(c)}{detail}"


def build_criteria_prompt(task_statement: str, criteria: list[Any]) -> str:
    """Step 3's user message: the task statement and the criteria, described
    in full (statement + how each is checked). Never the world."""
    crit_lines = "\n".join(f"{i}. {_describe_criterion(c)}" for i, c in enumerate(criteria, 1))
    return f"# Task statement\n\n{task_statement.strip()}\n\n# Acceptance criteria\n\n{crit_lines}\n"


def build_evidence_prompt(task_statement: str, criteria: list[Any], observations: list[str]) -> str:
    """Step 2's user message: the task statement, the bare criteria statements
    (no verification detail — the judge here is reading evidence, not
    checking assessability), and the rendered observations."""
    crit_lines = "\n".join(f"{i}. {_criterion_statement(c)}" for i, c in enumerate(criteria, 1))
    obs = "\n\n".join(observations) or "(nothing observable was named)"
    return (
        f"# Task statement\n\n{task_statement.strip()}\n\n"
        f"# Acceptance criteria\n\n{crit_lines}\n\n"
        f"# Observed world (delta since filing, then current content)\n\n{obs}\n"
    )
