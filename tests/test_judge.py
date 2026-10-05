"""T3.2 — the selectable judge runners behind one `Judge` interface.

Covers: (a) `load_config` defaults and its unknown-judge refusal; (b)
`get_judge` resolves all five configured names; (c) `PydanticAIJudge` under a
FAKE pydantic-ai model produces valid judgments and a usage dict; (d) a keyed
runner with its env key ABSENT raises `JudgeUnavailable` at construction,
before any `Agent` is built or model call made; (e) `CliJudge`'s exact argv
for `claude-code` and `codex`, parsed from a FAKE subprocess; (f) a missing
binary, a non-zero exit, and unparsable output each raise `JudgeUnavailable`
and nothing else; (g) the graph: a raising judge makes `complete_workitem`
return `unverifiable` with the criteria step `uncertain`, and the run
record's `judge` field carries the configured runner's name; (h) `none`
still returns `uncertain` judgments, unchanged.

No real model call and no real `claude`/`codex` invocation anywhere in this
file — every external boundary is faked.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from hyperspace.config import DEFAULT_MODELS, JUDGES, Config, load_config, write_config
from hyperspace.contracts.candidate import AcceptanceCriterion
from hyperspace.judge import (
    CliJudge,
    CriteriaJudgment,
    Judge,
    JudgeUnavailable,
    Judgment,
    NoneJudge,
    PydanticAIJudge,
    get_judge,
)

PROJECT = "demo-project"


# ── (a) load_config ──────────────────────────────────────────────────────


def test_load_config_defaults_when_absent(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg == Config(judge="none", model=None, port=8791, user="user", project_dir=tmp_path)


def test_load_config_reads_all_four_fields(tmp_path):
    (tmp_path / ".hyperspace").mkdir()
    (tmp_path / ".hyperspace" / "config.toml").write_text(
        'judge = "codex"\nmodel = "gpt-codex-5"\nport = 9000\nuser = "alice"\n'
    , encoding="utf-8")
    cfg = load_config(tmp_path)
    assert (cfg.judge, cfg.model, cfg.port, cfg.user) == ("codex", "gpt-codex-5", 9000, "alice")


def test_load_config_refuses_unknown_judge_naming_the_five(tmp_path):
    (tmp_path / ".hyperspace").mkdir()
    (tmp_path / ".hyperspace" / "config.toml").write_text('judge = "bogus"\n', encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_config(tmp_path)
    message = str(exc.value)
    for name in JUDGES:
        assert name in message


def test_write_config_round_trips(tmp_path):
    write_config(tmp_path, judge="anthropic", model="claude-x", port=8123, user="bob")
    cfg = load_config(tmp_path)
    assert (cfg.judge, cfg.model, cfg.port, cfg.user) == ("anthropic", "claude-x", 8123, "bob")


def test_write_config_preserves_unknown_top_level_keys(tmp_path):
    """A re-provision (`init --provision`, or the setup skill re-run) must
    never silently delete a coupling key `write_config` doesn't itself own —
    `worklog_owner` / `worklog_mirror_dir` / `worklog_default_project`
    (v0.1.1 part A + v0.1.2) are read raw by other modules and carry no
    field on `Config`; the joint plan with a sibling plugin rests on these
    surviving a config rewrite untouched (v0.1.2 fix)."""
    config_path = tmp_path / ".hyperspace" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        'judge = "none"\n'
        'port = 8791\n'
        'user = "user"\n'
        'worklog_owner = "technical-cofounder"\n'
        'worklog_mirror_dir = "worklog/entries"\n',
        encoding="utf-8",
    )

    write_config(tmp_path, port=9000)

    text = config_path.read_text(encoding="utf-8")
    assert 'worklog_owner = "technical-cofounder"' in text
    assert 'worklog_mirror_dir = "worklog/entries"' in text
    cfg = load_config(tmp_path)
    assert cfg.port == 9000


# ── (b) get_judge resolves all five ──────────────────────────────────────


def test_get_judge_resolves_all_five_names(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    for name in JUDGES:
        judge = get_judge(Config(judge=name))
        assert isinstance(judge, Judge)
        assert judge.name == name


# ── (c) PydanticAIJudge under a fake model ───────────────────────────────


def _criterion() -> AcceptanceCriterion:
    return AcceptanceCriterion(
        statement="The result file is created by the work.",
        verification={"kind": "file_state", "path": "out/result.txt", "assertion": "exists"},
    )


def test_pydantic_ai_judge_produces_valid_judgments_under_fake_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    from pydantic_ai.models.test import TestModel

    fake = TestModel(custom_output_args={
        "acceptable": True,
        "criteria": [{"statement": "x", "relevant": True, "assessable": True, "reason": "matches the task"}],
        "reason": "fine",
        "uncertain": False,
    })
    # OpenRouter validates `model` as `<upstream-provider>/<model>` at Agent
    # construction time regardless of `model_override` (pydantic-ai resolves
    # the model string eagerly) — empirically found this session; a bare
    # "test-model-id" raises `UserError` before the fake is ever consulted.
    runner = PydanticAIJudge("openrouter", model="test-provider/test-model-id", model_override=fake)
    assert runner.name == "openrouter"

    cq, usage = asyncio.run(runner.judge_criteria("task statement", [_criterion()]))
    assert isinstance(cq, CriteriaJudgment)
    assert cq.acceptable is True
    assert set(usage) == {"model", "input_tokens", "output_tokens", "requests"}
    assert usage["model"] == "openrouter:test-provider/test-model-id"

    fake.custom_output_args = {
        "accepted": True,
        "outcome_realized": True,
        "criteria": [{"statement": "x", "discharged": True, "evidence": "loader.py:6 quoted"}],
        "reason": "fine",
        "uncertain": False,
    }
    judgment, usage2 = asyncio.run(
        runner.judge_evidence("task statement", [_criterion()], ["--- out/result.txt ---\nresult\n"])
    )
    assert isinstance(judgment, Judgment)
    assert judgment.accepted is True
    assert set(usage2) == {"model", "input_tokens", "output_tokens", "requests"}


@pytest.mark.parametrize("provider", ["openrouter", "anthropic"])
def test_pydantic_ai_judge_default_models_are_configured(provider):
    assert provider in DEFAULT_MODELS
    assert isinstance(DEFAULT_MODELS[provider], str) and DEFAULT_MODELS[provider]


# ── (d) missing env key → JudgeUnavailable, before any Agent/model call ──


@pytest.mark.parametrize(
    "provider, env_var", [("openrouter", "OPENROUTER_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")]
)
def test_pydantic_ai_judge_raises_without_key(monkeypatch, provider, env_var):
    monkeypatch.delenv(env_var, raising=False)
    # A fake model is supplied to prove the raise happens BEFORE it is ever
    # consulted: construction never reaches the point of building an Agent,
    # so no network call is possible regardless of what model_override holds.
    from pydantic_ai.models.test import TestModel

    with pytest.raises(JudgeUnavailable) as exc:
        PydanticAIJudge(provider, model_override=TestModel())
    assert exc.value.runner == provider
    assert env_var in exc.value.reason


# ── (e) CliJudge argv, (f) failure modes ─────────────────────────────────


_VALID_CQ_PAYLOAD = {
    "acceptable": True,
    "criteria": [{"statement": "x", "relevant": True, "assessable": True, "reason": "ok"}],
    "reason": "ok",
    "uncertain": False,
}


def _fake_which_present(binary: str) -> str | None:
    return f"/usr/local/bin/{binary}"


def _fake_run_ok(kind: str, payload: dict, captured: dict):
    def _run(argv, **kwargs):
        captured["argv"] = argv
        if kind == "codex":
            idx = argv.index("--output-last-message")
            Path(argv[idx + 1]).write_text(json.dumps(payload), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
    return _run


@pytest.mark.parametrize("kind", ["claude-code", "codex"])
def test_cli_judge_argv_and_parses_valid_json(kind):
    captured: dict = {}
    runner = CliJudge(kind, run=_fake_run_ok(kind, _VALID_CQ_PAYLOAD, captured), which=_fake_which_present)
    cq, usage = asyncio.run(runner.judge_criteria("task statement", [_criterion()]))
    assert isinstance(cq, CriteriaJudgment)
    assert cq.acceptable is True
    assert usage == {"model": kind, "input_tokens": 0, "output_tokens": 0, "requests": 1}

    argv = captured["argv"]
    if kind == "claude-code":
        # argv[0] is what `which` resolved, never the bare name: on Windows an
        # npm-installed CLI is a `.cmd` shim that CreateProcess cannot find by
        # bare name (v0.1.3).
        assert argv[0] == "/usr/local/bin/claude"
        assert argv[1] == "-p"
        assert isinstance(argv[2], str) and "task statement" in argv[2]
        assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
        assert "--system-prompt" in argv
        assert "--json-schema" in argv
    else:
        assert argv[0:2] == ["/usr/local/bin/codex", "exec"]
        assert "--output-schema" in argv
        assert "--output-last-message" in argv
        assert isinstance(argv[-1], str) and "task statement" in argv[-1]


@pytest.mark.parametrize("kind", ["claude-code", "codex"])
def test_cli_judge_runs_the_resolved_windows_shim_path(kind):
    """An npm-installed CLI on Windows is `<name>.cmd`; `which` finds it via
    PATHEXT, and that resolved path — not the bare name — is what runs."""
    binary = "claude" if kind == "claude-code" else "codex"
    shim = f"C:/Users/u/AppData/Roaming/npm/{binary}.cmd"
    captured: dict = {}
    runner = CliJudge(kind, run=_fake_run_ok(kind, _VALID_CQ_PAYLOAD, captured), which=lambda b: shim)
    asyncio.run(runner.judge_criteria("task statement", [_criterion()]))
    assert captured["argv"][0] == shim


@pytest.mark.parametrize("kind", ["claude-code", "codex"])
def test_cli_judge_missing_binary_raises_judge_unavailable(kind):
    runner = CliJudge(kind, run=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")),
                       which=lambda binary: None)
    with pytest.raises(JudgeUnavailable) as exc:
        asyncio.run(runner.judge_criteria("task statement", [_criterion()]))
    assert exc.value.runner == kind


@pytest.mark.parametrize("kind", ["claude-code", "codex"])
def test_cli_judge_nonzero_exit_raises_judge_unavailable(kind):
    def _run(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")
    runner = CliJudge(kind, run=_run, which=_fake_which_present)
    with pytest.raises(JudgeUnavailable) as exc:
        asyncio.run(runner.judge_criteria("task statement", [_criterion()]))
    assert exc.value.runner == kind
    assert "boom" in exc.value.reason


@pytest.mark.parametrize("kind", ["claude-code", "codex"])
def test_cli_judge_unparsable_output_raises_judge_unavailable(kind):
    def _run(argv, **kwargs):
        if kind == "codex":
            idx = argv.index("--output-last-message")
            Path(argv[idx + 1]).write_text("not json at all", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="not json at all", stderr="")
    runner = CliJudge(kind, run=_run, which=_fake_which_present)
    with pytest.raises(JudgeUnavailable) as exc:
        asyncio.run(runner.judge_criteria("task statement", [_criterion()]))
    assert exc.value.runner == kind


def test_cli_judge_claude_envelope_with_result_field_is_unwrapped():
    """`claude -p --output-format json --json-schema …` wraps its answer in an
    envelope whose `result` is the answer's JSON as a string (register A19,
    seen on a real call with claude 2.1.285, 2026-10-05). This asserts that
    string-wrapped-JSON form."""
    captured: dict = {}

    def _run(argv, **kwargs):
        captured["argv"] = argv
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": json.dumps(_VALID_CQ_PAYLOAD)}), stderr="")

    runner = CliJudge("claude-code", run=_run, which=_fake_which_present)
    cq, _ = asyncio.run(runner.judge_criteria("task statement", [_criterion()]))
    assert isinstance(cq, CriteriaJudgment)
    assert cq.acceptable is True


# The model flag each CLI documents in its own `--help` (claude 2.1.285:
# "--model <model> … an alias for the latest model (e.g. 'fable', 'opus', or
# 'sonnet')"; codex-cli 0.145.0 `exec`: "-m, --model <MODEL>").
_MODEL_FLAG = {"claude-code": "--model", "codex": "-m"}


@pytest.mark.parametrize("kind", ["claude-code", "codex"])
def test_cli_judge_passes_the_configured_model(kind):
    captured: dict = {}
    runner = CliJudge(kind, model="sonnet", run=_fake_run_ok(kind, _VALID_CQ_PAYLOAD, captured),
                      which=_fake_which_present)
    asyncio.run(runner.judge_criteria("task statement", [_criterion()]))
    argv = captured["argv"]
    flag = _MODEL_FLAG[kind]
    assert flag in argv
    assert argv[argv.index(flag) + 1] == "sonnet"


@pytest.mark.parametrize("kind", ["claude-code", "codex"])
def test_cli_judge_without_a_model_leaves_the_choice_to_the_cli(kind):
    captured: dict = {}
    runner = CliJudge(kind, run=_fake_run_ok(kind, _VALID_CQ_PAYLOAD, captured), which=_fake_which_present)
    asyncio.run(runner.judge_criteria("task statement", [_criterion()]))
    assert _MODEL_FLAG[kind] not in captured["argv"]


@pytest.mark.parametrize("kind", ["claude-code", "codex"])
def test_get_judge_hands_the_configured_model_to_the_cli_judge(kind):
    assert get_judge(Config(judge=kind, model="sonnet")).model == "sonnet"
    assert get_judge(Config(judge=kind)).model is None


@pytest.mark.parametrize("kind", ["claude-code", "codex"])
def test_cli_judge_child_gets_no_stdin_and_no_session_marker(kind, monkeypatch):
    """Inside the engine's MCP server, stdin is the JSON-RPC pipe: a child
    that inherits it can read the server's next request (observed: `claude
    -p` waits 3 s on an inherited stdin). `CLAUDECODE` marks the calling
    Claude Code session; the judge is a session of its own."""
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("HYPERSPACE_TEST_KEPT", "yes")
    captured: dict = {}

    def _run(argv, **kwargs):
        captured.update(kwargs)
        return _fake_run_ok(kind, _VALID_CQ_PAYLOAD, {})(argv, **kwargs)

    runner = CliJudge(kind, run=_run, which=_fake_which_present)
    asyncio.run(runner.judge_criteria("task statement", [_criterion()]))
    assert captured["stdin"] is subprocess.DEVNULL
    assert "CLAUDECODE" not in captured["env"]
    assert captured["env"]["HYPERSPACE_TEST_KEPT"] == "yes"


# ── (g) graph coupling: a raising judge → unverifiable, criteria uncertain ──


def _git(root: Path, *args: str, date: str | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else None
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=root, check=True, capture_output=True, encoding="utf-8", errors="replace", env=env,
    )


def _ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


class _RaisingJudge:
    """A `Judge` that always raises `JudgeUnavailable` — proves the graph
    coupling without depending on any real runner's construction."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def judge_criteria(self, task, criteria):
        raise JudgeUnavailable(self.name, f"{self.name} is not configured in this test")

    async def judge_evidence(self, task, criteria, observations):
        raise AssertionError("evidence judge must not be reached — criteria fails first")


@pytest.fixture
def project(tmp_path):
    from hyperspace.store import Store

    root = tmp_path / "proj"
    root.mkdir()
    (root / ".gitignore").write_text(".hyperspace/\n", encoding="utf-8")
    (root / "README.md").write_text("demo\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init", date=_ago(120))
    store = Store.init(root / ".hyperspace" / "graph.db")
    store.upsert_project(code=PROJECT, name="Demo")
    try:
        yield root, store
    finally:
        store.close()


def _file_row(store, ext: str) -> dict:
    from hyperspace.tools import call_tool

    result = call_tool(store, "upsert_work_item", {
        "project": PROJECT, "external_id": ext, "name": "Produce the result file",
        "type": "task", "state": "ready", "parent_work_item": None, "assignee_agent": None,
        "team": None, "idempotency_key": f"{ext}-create",
        "specification": {
            "problem": "The project has no result file, so nothing downstream can read the outcome.",
            "why_it_matters": "Downstream steps read out/result.txt; without it they have nothing to consume.",
            "context_pointer": "tests/test_judge.py fixture.",
        },
        "source_references": [{"uri": "tests/test_judge.py"}],
        "effort_level": "quick", "module": None,
        "acceptance_criteria": [{
            "statement": "The result file is created by the work.",
            "verification": {"kind": "file_state", "path": "out/result.txt", "assertion": "exists"},
        }],
        "proposer_identity": "engineer", "proposer_surface": "cli-mac", "uncertainty_notes": [],
    })
    assert "error" not in result, result
    return result


def test_raising_judge_makes_graph_unverifiable_with_criteria_uncertain(project):
    from hyperspace.verify import CompletionClaim, complete_workitem, local_deps

    root, store = project
    _file_row(store, f"{PROJECT}:g")
    (root / "out").mkdir(parents=True, exist_ok=True)
    (root / "out" / "result.txt").write_text("result\n", encoding="utf-8")

    judge = _RaisingJudge("openrouter")
    deps = local_deps(store, judge, project_root=root)
    claim = CompletionClaim(
        project=PROJECT, external_id=f"{PROJECT}:g",
        touched=[{"path": "out/result.txt", "effect": "created"}],
        idempotency_key=f"{PROJECT}:g-done", proposer_identity="engineer", proposer_surface="cli-mac",
    )
    out = asyncio.run(complete_workitem(claim, deps))

    assert out["outcome"] == "unverifiable", out
    assert out["steps"]["criteria"]["status"] == "uncertain"
    run = store.get_verifier_run(out["run_id"])
    assert run["judge"] == "openrouter"
    row = store.get_work_item(external_id=f"{PROJECT}:g", project_code=PROJECT)
    assert row["state"] == "ready"


# ── (h) none runner unchanged ────────────────────────────────────────────


def test_none_runner_still_returns_uncertain():
    none_judge = NoneJudge()
    assert none_judge.name == "none"
    cq, cq_usage = asyncio.run(none_judge.judge_criteria("t", [_criterion()]))
    assert cq.uncertain is True and cq.acceptable is False
    judgment, j_usage = asyncio.run(none_judge.judge_evidence("t", [_criterion()], []))
    assert judgment.uncertain is True and judgment.accepted is False
