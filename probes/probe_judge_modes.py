#!/usr/bin/env python3
"""probes/probe_judge_modes.py — T7: the verifier's judge follows the
configured runner. The keyless (`none`) path is exercised always: it closes
a deterministic criterion `done`, and reports an unattested `manual`
criterion as `unverifiable` — awaiting attestation, never "failed to start".
The four keyed/CLI branches (`anthropic`, `openrouter`, `claude-code`,
`codex`) are exercised only when their key/binary is present AND `--no-paid`
is absent; every branch that runs is proven by reading its OWN run record
back out of `verifier_runs` (`store.get_verifier_run(run_id)["judge"]`) — not
by trusting the claim, per this system's whole reason for existing.

`--no-paid` disables all four keyed/CLI branches, not only the two the brief
names explicitly: `claude-code`/`codex` nest a `claude -p`/`codex exec` call
inside THIS Claude Code session, which the brief's Out-of-scope section
forbids outright ("no `claude -p` / interactive `claude` runs") and register
A19 defers to the test session. The controller reruns this probe without
`--no-paid` there, under the maintainer's real provider keys, on a machine
where that nesting is the thing being tested.

Usage: imported by probes/run.py; PROBE = "judge_modes"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROBE = "judge_modes"
PROJECT = "judge-modes-probe"


def _candidate(ext: str, criteria: list[dict], idem: str) -> dict:
    return {
        "project": PROJECT, "external_id": ext, "name": "Judge modes probe item",
        "type": "task", "state": "ready", "parent_work_item": None,
        "assignee_agent": None, "team": None, "idempotency_key": idem,
        "specification": {
            "problem": "The judge-modes probe needs a real filed row to close through each runner.",
            "why_it_matters": "Without a real filing there is nothing for complete_workitem to verify.",
            "context_pointer": "probes/probe_judge_modes.py",
        },
        "source_references": [{"uri": "probes/probe_judge_modes.py"}],
        "effort_level": "quick", "module": None,
        "acceptance_criteria": criteria,
        "proposer_identity": "probe", "proposer_surface": "cli-mac",
        "uncertainty_notes": [],
    }


async def _run_none_branch(project_dir: Path, evidence: dict) -> bool:
    from hyperspace.judge import NoneJudge
    from hyperspace.store import Store
    from hyperspace.tools import call_tool
    from hyperspace.verify import CompletionClaim, complete_workitem, local_deps

    db_path = project_dir / ".hyperspace" / "graph.db"
    store = Store.init(db_path)
    try:
        result = call_tool(store, "upsert_project", {"code": PROJECT, "name": "Judge modes probe"})
        if "error" in result:
            evidence["none_error"] = result["error"]
            return False

        # (1) one deterministic file_state criterion -> done, none judge.
        ext1 = f"{PROJECT}:det"
        det_criterion = {
            "statement": "The result file is created by the work.",
            "verification": {"kind": "file_state", "path": "out/det.txt", "assertion": "exists"},
        }
        filed = call_tool(store, "upsert_work_item", _candidate(ext1, [det_criterion], "det-create"))
        if "error" in filed:
            evidence["none_error"] = filed["error"]
            return False
        (project_dir / "out").mkdir(parents=True, exist_ok=True)
        (project_dir / "out" / "det.txt").write_text("result\n", encoding="utf-8")

        deps = local_deps(store, NoneJudge(), project_root=project_dir)
        claim1 = CompletionClaim(
            project=PROJECT, external_id=ext1,
            touched=[{"path": "out/det.txt", "effect": "created"}],
            idempotency_key="det-done", proposer_identity="probe", proposer_surface="cli-mac",
        )
        out1 = await complete_workitem(claim1, deps)
        run1 = store.get_verifier_run(out1["run_id"])
        det_ok = out1["outcome"] == "done" and run1 is not None and run1.get("judge") == "none"
        evidence["none_deterministic"] = {
            "outcome": out1["outcome"], "run_id": out1["run_id"],
            "run_record_judge": run1.get("judge") if run1 else None,
        }

        # (2) manual criterion, no attestation -> unverifiable, "awaiting
        # attestation" — never a start failure.
        ext2 = f"{PROJECT}:manual"
        # A DIFFERENT deterministic criterion than det_criterion's — that one
        # names out/det.txt, already true-at-filing by the time this row is
        # filed (written by the branch above), which would REFUSE this row
        # before the manual criterion is ever assessed. A fresh path keeps
        # this row's only interesting criterion the manual one.
        det2_criterion = {
            "statement": "A second result file is created by the work.",
            "verification": {"kind": "file_state", "path": "out/det2.txt", "assertion": "exists"},
        }
        manual_criterion = {
            "statement": "The user has read the result file and confirms it is right.",
            "verification": {"kind": "manual", "instruction": "Open out/man.txt and confirm it reads right."},
        }
        filed2 = call_tool(store, "upsert_work_item", _candidate(ext2, [det2_criterion, manual_criterion], "man-create"))
        if "error" in filed2:
            evidence["none_error_manual"] = filed2["error"]
            return False
        (project_dir / "out" / "man.txt").write_text("result\n", encoding="utf-8")
        (project_dir / "out" / "det2.txt").write_text("result\n", encoding="utf-8")

        claim2 = CompletionClaim(
            project=PROJECT, external_id=ext2,
            touched=[
                {"path": "out/man.txt", "effect": "created"},
                {"path": "out/det2.txt", "effect": "created"},
            ],
            idempotency_key="man-done", proposer_identity="probe", proposer_surface="cli-mac",
        )
        out2 = await complete_workitem(claim2, deps)
        landing_detail = out2.get("steps", {}).get("landing", {}).get("detail", "")
        manual_ok = (
            out2["outcome"] == "unverifiable"
            and "awaiting" in landing_detail and "attestation" in landing_detail
            and "failed to start" not in landing_detail
        )
        evidence["none_manual"] = {
            "outcome": out2["outcome"], "run_id": out2["run_id"], "landing_detail": landing_detail,
        }

        return bool(det_ok and manual_ok)
    finally:
        store.close()


async def _run_keyed_branch(judge_name: str, project_dir: Path) -> dict:
    from hyperspace.config import Config
    from hyperspace.judge import JudgeUnavailable, get_judge
    from hyperspace.store import Store
    from hyperspace.tools import call_tool
    from hyperspace.verify import CompletionClaim, complete_workitem, local_deps

    db_path = project_dir / ".hyperspace" / f"graph-{judge_name}.db"
    store = Store.init(db_path)
    try:
        result = call_tool(store, "upsert_project", {"code": PROJECT, "name": "Judge modes probe"})
        if "error" in result:
            return {"ran": True, "ok": False, "reason": result["error"]}

        ext = f"{PROJECT}:{judge_name}"
        criterion = {
            "statement": "out/result.txt exists and its content is the word 'result'.",
            "verification": {"kind": "file_state", "path": "out/result.txt", "assertion": "exists"},
        }
        filed = call_tool(store, "upsert_work_item", _candidate(ext, [criterion], f"{judge_name}-create"))
        if "error" in filed:
            return {"ran": True, "ok": False, "reason": filed["error"]}
        (project_dir / "out").mkdir(parents=True, exist_ok=True)
        (project_dir / "out" / "result.txt").write_text("result\n", encoding="utf-8")

        try:
            judge = get_judge(Config(judge=judge_name))
        except JudgeUnavailable as exc:
            return {"ran": False, "reason": f"unavailable: {exc.reason}"}

        deps = local_deps(store, judge, project_root=project_dir)
        claim = CompletionClaim(
            project=PROJECT, external_id=ext,
            touched=[{"path": "out/result.txt", "effect": "created"}],
            idempotency_key=f"{judge_name}-done", proposer_identity="probe", proposer_surface="cli-mac",
        )
        out = await complete_workitem(claim, deps)
        run = store.get_verifier_run(out["run_id"])
        run_judge = run.get("judge") if run else None
        ok = run_judge == judge_name and out["outcome"] in ("done", "unverifiable")
        return {
            "ran": True, "ok": ok, "outcome": out["outcome"], "run_id": out["run_id"],
            "run_record_judge": run_judge,
        }
    finally:
        store.close()


def run(out_dir, opts) -> bool:
    evidence: dict = {}
    branch_results: dict = {}

    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        none_ok = asyncio.run(_run_none_branch(project_dir, evidence))

        for judge_name, env_var in (("anthropic", "ANTHROPIC_API_KEY"), ("openrouter", "OPENROUTER_API_KEY")):
            if getattr(opts, "no_paid", False):
                branch_results[judge_name] = {"ran": False, "reason": "--no-paid"}
                continue
            if not os.environ.get(env_var):
                branch_results[judge_name] = {"ran": False, "reason": f"{env_var} not set"}
                continue
            branch_results[judge_name] = asyncio.run(_run_keyed_branch(judge_name, project_dir))

        for judge_name, binary in (("claude-code", "claude"), ("codex", "codex")):
            present = shutil.which(binary) is not None
            if getattr(opts, "no_paid", False):
                branch_results[judge_name] = {
                    "ran": False, "binary_present": present,
                    "reason": "--no-paid (nests a claude/codex CLI call inside this Claude Code "
                              "session; Out-of-scope forbids that here — the test session "
                              "verifies the nesting under register A19)",
                }
                continue
            if not present:
                branch_results[judge_name] = {"ran": False, "binary_present": present, "reason": f"{binary!r} not on PATH"}
                continue
            branch_results[judge_name] = asyncio.run(_run_keyed_branch(judge_name, project_dir))

    evidence["branches"] = branch_results
    every_ran_branch_ok = all(b.get("ok", True) for b in branch_results.values() if b.get("ran"))
    ok = bool(none_ok) and every_ran_branch_ok

    write_verdict(Path(out_dir) / f"{PROBE}.json", probe=PROBE, result="PASS" if ok else "FAIL", evidence=evidence)
    return ok
