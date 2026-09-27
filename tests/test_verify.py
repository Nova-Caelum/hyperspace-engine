"""T3.1 — the verification graph: the five-step closure pipeline as a pydantic
graph over the local store.

Covers: (a) the graph's five named nodes; (b) `local_deps` returns a `Deps`;
(c) a landing-discharged `file_state exists` row closes `done` under the `none`
judge with `completed_by` set; (d) an unattested `manual` criterion reads
`unverifiable`; (e) the same with a matching attestation reads `done`;
(f) a file already present at filing never reads `done`; (g) a second close on a
`done` row reads `already_done`; (h) a touched path that does not exist is
`refused` with a repair; (i) the run record carries every junction; (j) a judge
that raises is retried once, then `uncertain` -> `unverifiable`; (k) a `none`
run whose landing cannot discharge reads `unverifiable` with both semantic steps
`skipped`.

The contract refuses an all-`manual` criteria set, so the `manual` rows carry
one landing-dischargeable `file_state` criterion beside the manual one.
"""
import asyncio
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pydantic_graph

from hyperspace.store import Store
from hyperspace.tools import call_tool

PROJECT = "demo-project"
MANUAL_STATEMENT = "The user has read the result file and confirms it is right."


# ── fixtures ────────────────────────────────────────────────────────────────


def _git(root: Path, *args: str, date: str | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else None
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=root, check=True, capture_output=True, text=True, env=env,
    )


def _ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


@pytest.fixture
def project(tmp_path):
    """A user project: a git checkout with one commit, holding `.hyperspace/`."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".gitignore").write_text(".hyperspace/\nignored/\n")
    (root / "README.md").write_text("demo\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init", date=_ago(120))
    store = Store.init(root / ".hyperspace" / "graph.db")
    store.upsert_project(code=PROJECT, name="Demo")
    try:
        yield root, store
    finally:
        store.close()


def _file_state(path: str, statement: str = "The result file is created by the work.") -> dict:
    return {"statement": statement,
            "verification": {"kind": "file_state", "path": path, "assertion": "exists"}}


def _manual() -> dict:
    return {"statement": MANUAL_STATEMENT,
            "verification": {"kind": "manual", "instruction": "Open out/result.txt and confirm it reads right."}}


def _file_row(store: Store, ext: str, criteria: list[dict]) -> dict:
    result = call_tool(store, "upsert_work_item", {
        "project": PROJECT,
        "external_id": ext,
        "name": "Produce the result file",
        "type": "task",
        "state": "ready",
        "parent_work_item": None,
        "assignee_agent": None,
        "team": None,
        "idempotency_key": f"{ext}-create",
        "specification": {
            "problem": "The project has no result file, so nothing downstream can read the outcome.",
            "why_it_matters": "Downstream steps read out/result.txt; without it they have nothing to consume.",
            "context_pointer": "tests/test_verify.py fixture.",
        },
        "source_references": [{"uri": "tests/test_verify.py"}],
        "effort_level": "quick",
        "module": None,
        "acceptance_criteria": criteria,
        "proposer_identity": "engineer",
        "proposer_surface": "cli-mac",
        "uncertainty_notes": [],
    })
    assert "error" not in result, result
    return result


def _write(root: Path, rel: str, text: str = "result\n") -> None:
    # Linux stamps mtime from the coarse kernel clock (one jiffy, up to 10 ms
    # behind the fine clock the row's filed_at uses); a write in the same
    # jiffy as the filing can read as "not after filing". Real sessions put
    # seconds between filing and writing — the tests put 20 ms.
    time.sleep(0.02)
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _claim(ext: str, touched=("out/result.txt",), attestations=()):
    from hyperspace.verify import CompletionClaim, ManualAttestation
    return CompletionClaim(
        project=PROJECT, external_id=ext,
        touched=[{"path": p, "effect": "created"} for p in touched],
        idempotency_key=f"{ext}-done", proposer_identity="engineer", proposer_surface="cli-mac",
        manual_attestations=[ManualAttestation(**a) for a in attestations],
    )


def _run(claim, deps) -> dict:
    from hyperspace.verify import complete_workitem
    return asyncio.run(complete_workitem(claim, deps))


def _none_deps(store, root, **kw):
    from hyperspace.judge import NoneJudge
    from hyperspace.verify import local_deps
    return local_deps(store, NoneJudge(), project_root=root, **kw)


FULL_TRAIL = ["received", "vetted", "criteria_checked", "landing_checked", "comprehended", "composed"]


# ── (a) (b) shape ───────────────────────────────────────────────────────────


def test_graph_exposes_five_named_nodes():
    from pydantic_graph.step import NodeStep

    from hyperspace.verify.graph import verification_graph
    assert isinstance(verification_graph, pydantic_graph.Graph)
    names = sorted(n.node_type.__name__ for n in verification_graph.nodes.values() if isinstance(n, NodeStep))
    assert names == ["Commit", "CriteriaQuality", "EvidenceJudge", "Landing", "Vet"]


def test_local_deps_returns_deps(project):
    root, store = project
    from hyperspace.verify import Deps
    deps = _none_deps(store, root)
    assert isinstance(deps, Deps)
    assert deps.judge_name == "none"
    assert deps.project_root == root.resolve()
    assert deps.user_identity == "user"


def test_local_deps_defaults_project_root_from_store(project):
    root, store = project
    from hyperspace.judge import NoneJudge
    from hyperspace.verify import local_deps
    deps = local_deps(store, NoneJudge())
    assert deps.project_root == root.resolve()


def test_user_identity_read_from_config(project):
    root, store = project
    (root / ".hyperspace" / "config.toml").write_text('user = "alice"\n')
    assert _none_deps(store, root).user_identity == "alice"


# ── (c) done ────────────────────────────────────────────────────────────────


def test_done_path_none_judge(project):
    root, store = project
    _file_row(store, "demo-project:c", [_file_state("out/result.txt")])
    _write(root, "out/result.txt")
    out = _run(_claim("demo-project:c"), _none_deps(store, root))
    assert out["outcome"] == "done", out
    assert out["readback_state"] == "done"
    assert out["model_calls"] == 0
    row = store.get_work_item(external_id="demo-project:c", project_code=PROJECT)
    assert row["state"] == "done"
    assert row["completed_by"] == "hyperspace-verifier"


# ── (d) (e) manual ──────────────────────────────────────────────────────────


def test_unattested_manual_is_unverifiable(project):
    root, store = project
    _file_row(store, "demo-project:d", [_file_state("out/result.txt"), _manual()])
    _write(root, "out/result.txt")
    out = _run(_claim("demo-project:d"), _none_deps(store, root))
    assert out["outcome"] == "unverifiable", out
    assert out["steps"]["landing"]["status"] == "uncertain"
    assert store.get_work_item(external_id="demo-project:d", project_code=PROJECT)["state"] == "ready"


def test_attested_manual_is_done(project):
    root, store = project
    _file_row(store, "demo-project:e", [_file_state("out/result.txt"), _manual()])
    _write(root, "out/result.txt")
    att = [{"statement": MANUAL_STATEMENT, "attested_by": "user", "verbatim": "yes, confirmed"}]
    out = _run(_claim("demo-project:e", attestations=att), _none_deps(store, root))
    assert out["outcome"] == "done", out


def test_manual_attested_by_someone_else_is_not_done(project):
    root, store = project
    _file_row(store, "demo-project:e2", [_file_state("out/result.txt"), _manual()])
    _write(root, "out/result.txt")
    att = [{"statement": MANUAL_STATEMENT, "attested_by": "an-agent", "verbatim": "yes"}]
    out = _run(_claim("demo-project:e2", attestations=att), _none_deps(store, root))
    assert out["outcome"] == "unverifiable", out


# ── (f) already true at filing ──────────────────────────────────────────────


def test_file_present_before_filing_is_not_done(project):
    root, store = project
    _write(root, "out/result.txt")
    _file_row(store, "demo-project:f", [_file_state("out/result.txt")])
    out = _run(_claim("demo-project:f"), _none_deps(store, root))
    # Untracked and not after filing: landing cannot credit it -> `uncertain`.
    assert out["outcome"] == "unverifiable", out
    assert "filing" in out["steps"]["landing"]["detail"]
    assert store.get_work_item(external_id="demo-project:f", project_code=PROJECT)["state"] == "ready"


def test_committed_before_filing_is_refused(project):
    root, store = project
    _write(root, "out/result.txt")
    _git(root, "add", ".")
    # Git dates have 1-second resolution and the verifier counts a commit in the
    # filing's own second as "since filing" (canonical `_partition_filing_second`),
    # so the pre-existing commit is dated clearly before the filing.
    _git(root, "commit", "-q", "-m", "pre-existing", date=_ago(60))
    _file_row(store, "demo-project:f2", [_file_state("out/result.txt")])
    out = _run(_claim("demo-project:f2"), _none_deps(store, root))
    assert out["outcome"] == "refused", out
    assert "already true at filing" in out["reason"]


def test_criteria_update_restarts_the_delta_window(project):
    """filed_at is the FILING's timestamp: a criteria update mints a new filing,
    so a file created before the update but after the first filing predates it."""
    root, store = project
    _file_row(store, "demo-project:w", [_file_state("out/result.txt")])
    _write(root, "out/result.txt")
    payload_crit = [_file_state("out/result.txt", statement="The result file is created, per the update.")]
    from hyperspace.tools.work_items import upsert_work_item
    first = store.latest_filing("demo-project:w")
    upsert_work_item(store, **{
        "project": PROJECT, "external_id": "demo-project:w", "name": "Produce the result file",
        "type": "task", "state": "ready", "parent_work_item": None, "assignee_agent": None,
        "team": None, "idempotency_key": "demo-project:w-create",
        "specification": {
            "problem": "The project has no result file, so nothing downstream can read the outcome.",
            "why_it_matters": "Downstream steps read out/result.txt; without it they have nothing to consume.",
            "context_pointer": "tests/test_verify.py fixture.",
        },
        "source_references": [{"uri": "tests/test_verify.py"}], "effort_level": "quick", "module": None,
        "acceptance_criteria": payload_crit, "proposer_identity": "engineer", "proposer_surface": "cli-mac",
        "uncertainty_notes": [], "update_acceptance_criteria": True,
    })
    assert store.latest_filing("demo-project:w")["id"] != first["id"]
    out = _run(_claim("demo-project:w"), _none_deps(store, root))
    assert out["outcome"] != "done", out


# ── (g) already_done ────────────────────────────────────────────────────────


def test_second_close_is_already_done(project):
    root, store = project
    _file_row(store, "demo-project:g", [_file_state("out/result.txt")])
    _write(root, "out/result.txt")
    deps = _none_deps(store, root)
    assert _run(_claim("demo-project:g"), deps)["outcome"] == "done"
    out = _run(_claim("demo-project:g"), deps)
    assert out["outcome"] == "already_done", out


# ── (h) missing touched path ────────────────────────────────────────────────


def test_missing_touched_path_is_refused(project):
    root, store = project
    _file_row(store, "demo-project:h", [_file_state("out/result.txt")])
    out = _run(_claim("demo-project:h", touched=("out/nope.txt",)), _none_deps(store, root))
    assert out["outcome"] == "refused", out
    assert "absent" in out["reason"] and "resubmit" in out["reason"]


def test_unknown_row_is_unverifiable(project):
    root, store = project
    out = _run(_claim("demo-project:nope"), _none_deps(store, root))
    assert out["outcome"] == "unverifiable", out


# ── (i) run record ──────────────────────────────────────────────────────────


def test_run_record_carries_every_junction(project):
    root, store = project
    _file_row(store, "demo-project:i", [_file_state("out/result.txt")])
    _write(root, "out/result.txt")
    out = _run(_claim("demo-project:i"), _none_deps(store, root))
    assert out["trail"][:6] == FULL_TRAIL
    run = store.get_verifier_run(out["run_id"])
    assert run is not None
    assert run["judge"] == "none"
    assert run["outcome"] == "done"
    assert run["finished_at"]
    trail = [t["step"] for t in run["steps"]["trail"]]
    for junction in FULL_TRAIL:
        assert junction in trail
    assert run["steps"]["steps"]["criteria"]["status"] == "skipped"
    assert run["steps"]["steps"]["evidence"]["status"] == "skipped"


# ── (j) judge errors ────────────────────────────────────────────────────────


class _RaisingJudge:
    name = "raising"

    def __init__(self):
        self.criteria_calls = 0

    async def judge_criteria(self, task, criteria):
        self.criteria_calls += 1
        raise RuntimeError("provider down")

    async def judge_evidence(self, task, criteria, observations):
        raise RuntimeError("provider down")


def test_judge_error_retries_once_then_uncertain(project):
    root, store = project
    from hyperspace.verify import local_deps
    _file_row(store, "demo-project:j", [_file_state("out/result.txt")])
    _write(root, "out/result.txt")
    judge = _RaisingJudge()
    out = _run(_claim("demo-project:j"), local_deps(store, judge, project_root=root))
    assert out["outcome"] == "unverifiable", out
    assert judge.criteria_calls == 2
    assert out["steps"]["criteria"]["status"] == "uncertain"
    assert store.get_verifier_run(out["run_id"])["judge"] == "raising"


class _PassingJudge:
    """A scripted non-`none` judge: the semantic steps run as canonical."""
    name = "scripted"

    def __init__(self):
        self.calls = []

    async def judge_criteria(self, task, criteria):
        from hyperspace.judge.judgments import CriteriaJudgment, CriterionQuality
        self.calls.append("criteria")
        return CriteriaJudgment(acceptable=True, reason="ok", criteria=[
            CriterionQuality(statement=c.statement, relevant=True, assessable=True, reason="ok") for c in criteria
        ]), {"model": "scripted"}

    async def judge_evidence(self, task, criteria, observations):
        from hyperspace.judge.judgments import CriterionJudgment, Judgment
        self.calls.append("evidence")
        assert observations and "out/result.txt" in observations[0]
        return Judgment(accepted=True, outcome_realized=True, reason="ok", criteria=[
            CriterionJudgment(statement=c.statement, discharged=True, evidence="out/result.txt line 1") for c in criteria
        ]), {"model": "scripted"}


def test_named_judge_runs_both_semantic_steps(project):
    root, store = project
    from hyperspace.verify import local_deps
    _file_row(store, "demo-project:j2", [_file_state("out/result.txt")])
    _write(root, "out/result.txt")
    judge = _PassingJudge()
    out = _run(_claim("demo-project:j2"), local_deps(store, judge, project_root=root))
    assert out["outcome"] == "done", out
    assert judge.calls == ["criteria", "evidence"]
    assert out["model_calls"] == 2


# ── (k) none + undischarged landing ─────────────────────────────────────────


def test_none_judge_undischarged_landing_is_unverifiable(project):
    root, store = project
    # `ignored/` is git-ignored and not named in the claim: whether the file
    # predates the row is unknowable, so landing is `uncertain`, not a pass.
    _file_row(store, "demo-project:k", [_file_state("ignored/x.txt")])
    _write(root, "ignored/x.txt")
    _write(root, "out/result.txt")
    out = _run(_claim("demo-project:k"), _none_deps(store, root))
    assert out["outcome"] == "unverifiable", out
    assert out["steps"]["landing"]["status"] == "uncertain"
    run = store.get_verifier_run(out["run_id"])
    assert run["steps"]["steps"]["criteria"]["status"] == "skipped"
    assert run["steps"]["steps"]["evidence"]["status"] == "skipped"
    assert store.get_work_item(external_id="demo-project:k", project_code=PROJECT)["state"] == "ready"


def test_none_judge_does_not_pretend_to_judge():
    from hyperspace.contracts import AcceptanceCriterion
    from hyperspace.judge import NoneJudge
    crit = [AcceptanceCriterion(**_file_state("out/result.txt"))]
    cq, _ = asyncio.run(NoneJudge().judge_criteria("t", crit))
    assert cq.uncertain and not cq.acceptable and "no judge" in cq.reason
    assert all(not (c.relevant or c.assessable) for c in cq.criteria)
    j, _ = asyncio.run(NoneJudge().judge_evidence("t", crit, []))
    assert j.uncertain and not j.accepted and "no judge" in j.reason
    assert all(not c.discharged for c in j.criteria)


class _EvidenceRaisingJudge(_PassingJudge):
    name = "evidence-raising"

    def __init__(self):
        super().__init__()
        self.evidence_calls = 0

    async def judge_evidence(self, task, criteria, observations):
        self.evidence_calls += 1
        raise RuntimeError("provider down")


def test_evidence_judge_error_retries_once_then_uncertain(project):
    root, store = project
    from hyperspace.verify import local_deps
    _file_row(store, "demo-project:j3", [_file_state("out/result.txt")])
    _write(root, "out/result.txt")
    judge = _EvidenceRaisingJudge()
    out = _run(_claim("demo-project:j3"), local_deps(store, judge, project_root=root))
    assert out["outcome"] == "unverifiable", out
    assert judge.evidence_calls == 2
    assert out["steps"]["evidence"]["status"] == "uncertain"
    assert store.get_work_item(external_id="demo-project:j3", project_code=PROJECT)["state"] == "ready"
