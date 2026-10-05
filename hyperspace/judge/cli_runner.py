"""`CliJudge` — the two CLI-backed runners, `claude-code` and `codex`.

Both share `pydantic_ai_runner`'s prompt construction (`_prompts.py`) and the
same typed judgment models; the CLI's stdout (or, for `codex`, its
`--output-last-message` file — see below) is parsed as JSON into those
models. A missing binary, a non-zero exit, a timeout, or unparsable output
each raise `JudgeUnavailable` — never any other exception, so the graph's
single retry-then-`uncertain` handling is all that ever sees this runner fail.

Exact argv, decided from each CLI's own `--help` output:

  * `claude-code` — `claude -p <prompt> --output-format json --system-prompt
    <instructions> --json-schema <schema> [--model <model>]`. `claude --help`
    documents `--output-format json` ("single result"), `--system-prompt
    <prompt>`, `--json-schema <schema>` ("JSON Schema for structured output
    validation") and `--model <model>` (an alias such as `sonnet`, or a full
    model name). Register A19, verified end to end on 2026-10-05 with claude
    2.1.285 (both judges, nested inside a Claude Code session): the envelope's
    `result` is the answer's JSON as a string, which `_extract_json_payload`
    unwraps; it also carries `structured_output` (the same answer as an
    object), `is_error`, and `usage` / `total_cost_usd`. A bare object still
    parses.
  * `codex` — `codex exec --skip-git-repo-check --output-schema <schema
    file> --output-last-message <output file> [-m <model>] <prompt>`. `codex
    exec --help` has NO `--output-format`/`--json-schema` flag at all — its
    real structured-output mechanism is `--output-schema <file>` (a JSON
    Schema file) plus `-o/--output-last-message <file>` (the file the
    agent's final message is written to), and `-m, --model <MODEL>` picks the
    model. The judgment JSON is read from that file, never from stdout.

`model` comes from `.hyperspace/config.toml`; with none set, the flag is left
off and the CLI uses its own default model.

Every child runs with stdin closed and without `CLAUDECODE`. Inside the
engine's MCP server, stdin is the JSON-RPC pipe: a child that inherits it can
read the server's next request (observed: `claude -p` waits 3 s on an
inherited stdin before it starts). `CLAUDECODE` marks the calling Claude
Code session, and the judge is a session of its own.

Both CLIs also get the judgment model's JSON Schema embedded directly in the
prompt text as a second, model-facing instruction (belt-and-braces: neither
CLI's schema flag has a verified enforcement guarantee at authoring time).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from ..contracts.candidate import AcceptanceCriterion
from ._prompts import build_criteria_prompt, build_evidence_prompt, load_prompt
from .base import JudgeUnavailable
from .judgments import CriteriaJudgment, Judgment

_TIMEOUT_SECONDS = 120
_MAX_ERROR_CHARS = 300  # never enough room for a leaked credential; see Out of scope

_BINARIES = {"claude-code": "claude", "codex": "codex"}
_MODEL_FLAGS = {"claude-code": "--model", "codex": "-m"}
# Removed from the child's environment: the Claude Code session marker.
_STRIPPED_ENV = ("CLAUDECODE",)


def _trim(text: str | None) -> str:
    return (text or "").strip()[:_MAX_ERROR_CHARS]


def _schema_instruction(model_cls: type[BaseModel]) -> str:
    schema = json.dumps(model_cls.model_json_schema())
    return (
        "\n\n# Output format\n\nRespond with ONLY a single JSON object matching "
        f"this JSON Schema exactly — no prose, no markdown code fence, nothing else:\n{schema}\n"
    )


def _extract_json_payload(text: str) -> Any:
    """A bare JSON object is accepted directly. An envelope carrying a
    `result` field (string or nested object) is unwrapped — the shape
    `claude -p --output-format json` is understood to use, per Decision.md,
    though the exact field name was not independently confirmed this
    session (register A19)."""
    stripped = (text or "").strip()
    if not stripped:
        raise ValueError("empty output")
    outer = json.loads(stripped)
    if isinstance(outer, dict) and "result" in outer:
        inner = outer["result"]
        if isinstance(inner, str):
            return json.loads(inner)
        if isinstance(inner, dict):
            return inner
    return outer


def _parse(text: str, model_cls: type[BaseModel]) -> BaseModel:
    payload = _extract_json_payload(text)
    return model_cls.model_validate(payload)


class CliJudge:
    """`kind` in {"claude-code", "codex"}; `model` is passed to the CLI when
    set. `run` replaces `subprocess.run` and `which` replaces `shutil.which`
    — the two injection points the fakes use; production defaults are the
    real calls."""

    def __init__(
        self,
        kind: str,
        *,
        model: str | None = None,
        run: Callable[..., Any] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        if kind not in _BINARIES:
            raise ValueError(f"unknown CLI judge kind {kind!r} — must be one of: claude-code, codex")
        self.name = kind
        self.model = model
        self._binary = _BINARIES[kind]
        self._run = run
        self._which = which

    async def judge_criteria(
        self, task: str, criteria: list[AcceptanceCriterion]
    ) -> tuple[CriteriaJudgment, dict]:
        prompt = build_criteria_prompt(task, criteria) + _schema_instruction(CriteriaJudgment)
        text = self._invoke(prompt, load_prompt("criteria_judge"), CriteriaJudgment)
        judgment = self._parse_or_raise(text, CriteriaJudgment)
        return judgment, self._usage()

    async def judge_evidence(
        self, task: str, criteria: list[AcceptanceCriterion], observations: list[str]
    ) -> tuple[Judgment, dict]:
        prompt = build_evidence_prompt(task, criteria, observations) + _schema_instruction(Judgment)
        text = self._invoke(prompt, load_prompt("evidence_judge"), Judgment)
        judgment = self._parse_or_raise(text, Judgment)
        return judgment, self._usage()

    # ── internals ────────────────────────────────────────────────────────

    def _usage(self) -> dict:
        # Token counts are not read: claude's envelope carries them (A19,
        # 2026-10-05) but codex's last-message file does not, so one request
        # is the one fact both runners can report.
        return {"model": self.name, "input_tokens": 0, "output_tokens": 0, "requests": 1}

    def _parse_or_raise(self, text: str, model_cls: type[BaseModel]) -> BaseModel:
        try:
            return _parse(text, model_cls)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise JudgeUnavailable(
                self.name, f"could not parse {self._binary} JSON output: {_trim(str(exc))}"
            ) from None

    def _invoke(self, prompt: str, instructions: str, model_cls: type[BaseModel]) -> str:
        # argv[0] is the path `which` resolved, never the bare name: on Windows
        # an npm-installed CLI is a `.cmd` shim that `which` finds via PATHEXT
        # but CreateProcess cannot find by bare name.
        executable = self._which(self._binary)
        if executable is None:
            raise JudgeUnavailable(self.name, f"{self._binary!r} is not on PATH")
        if self.name == "claude-code":
            return self._invoke_claude(executable, prompt, instructions, model_cls)
        return self._invoke_codex(executable, prompt, instructions, model_cls)

    def _model_args(self) -> list[str]:
        return [_MODEL_FLAGS[self.name], self.model] if self.model else []

    @staticmethod
    def _child_env() -> dict[str, str]:
        return {key: value for key, value in os.environ.items() if key not in _STRIPPED_ENV}

    def _run_subprocess(self, argv: list[str]) -> Any:
        try:
            # The CLIs answer in UTF-8 JSON; decoding with the Windows ANSI
            # code page would corrupt (or crash on) any non-ASCII evidence.
            return self._run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                             encoding="utf-8", errors="replace", timeout=_TIMEOUT_SECONDS,
                             env=self._child_env())
        except subprocess.TimeoutExpired:
            raise JudgeUnavailable(self.name, f"{self._binary} timed out after {_TIMEOUT_SECONDS}s") from None
        except OSError as exc:
            raise JudgeUnavailable(self.name, f"{self._binary} failed to start: {_trim(str(exc))}") from None

    def _invoke_claude(self, executable: str, prompt: str, instructions: str, model_cls: type[BaseModel]) -> str:
        argv = [
            executable, "-p", prompt,
            "--output-format", "json",
            "--system-prompt", instructions,
            "--json-schema", json.dumps(model_cls.model_json_schema()),
            *self._model_args(),
        ]
        result = self._run_subprocess(argv)
        if result.returncode != 0:
            raise JudgeUnavailable(self.name, f"claude exited {result.returncode}: {_trim(result.stderr)}")
        return result.stdout

    def _invoke_codex(self, executable: str, prompt: str, instructions: str, model_cls: type[BaseModel]) -> str:
        combined_prompt = f"{instructions}\n\n{prompt}"
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "schema.json"
            out_path = Path(tmp) / "last_message.txt"
            schema_path.write_text(json.dumps(model_cls.model_json_schema()), encoding="utf-8")
            argv = [
                executable, "exec", "--skip-git-repo-check",
                "--output-schema", str(schema_path),
                "--output-last-message", str(out_path),
                *self._model_args(),
                combined_prompt,
            ]
            result = self._run_subprocess(argv)
            if result.returncode != 0:
                raise JudgeUnavailable(self.name, f"codex exited {result.returncode}: {_trim(result.stderr)}")
            if not out_path.exists():
                raise JudgeUnavailable(self.name, "codex produced no --output-last-message file")
            return out_path.read_text(encoding="utf-8")
