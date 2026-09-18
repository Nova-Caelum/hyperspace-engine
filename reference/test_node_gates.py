"""Tests for T4.8's Build-node exit-gate check (`node_gates.py`) and its
wiring into `loop_state.py gate-pass`.

Decision: `AgentSecretBase/workspace/hyperspace-engine_new_sprintframework/
m4-loop/ExitGateDecision_T4.8_ChiefPM_2026-09-06.md`. Covers `check_executing`
directly (unit level), the CLI wiring in `loop_state.py gate-pass` (subprocess
level, matching `test_loop_state.py`'s `_run_cli` pattern), and the
`build-no-verdicts` refusal fixture through the `gate-binding` assertion
adapter (`assertions/gate_binding.py`, T2.5).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BIN_DIR = HERE.parents[1] / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import node_gates  # noqa: E402
import plan_lint  # noqa: E402 — T4.5: the draft fixture's precondition test lints its Plan.md

import loader  # noqa: E402 — framework root is on sys.path via conftest.py
from assertions import AssertionContext  # noqa: E402
from assertions.gate_binding import PASS_MARKERS, GateBindingAdapter  # noqa: E402

REPO_ROOT = HERE.parents[2]  # .../_agentOS
FIXTURE_DIR = HERE / "fixtures" / "exit-gate" / "build-no-verdicts"


def _run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BIN_DIR / "loop_state.py"), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _verification(
    *,
    external_id: str,
    project: str,
    status: str,
    updated_at: str,
    outcome: str | None = None,
    readback_state: str | None = None,
) -> dict[str, Any]:
    """Mirror the real verifier run-file top-level shape, per the fields the
    handoff names: `external_id`, `project`, `status`, `updated_at`,
    `final_result.{outcome,readback_state}`. Verified against real files at
    `~/NovaCaelum_code/graph-machine/run/verifications/` this session —
    `readback_state` is genuinely absent (not null) on an `unverifiable` run,
    so it is omitted here too unless the caller supplies one."""
    final_result: dict[str, Any] = {}
    if outcome is not None:
        final_result["outcome"] = outcome
    if readback_state is not None:
        final_result["readback_state"] = readback_state
    return {
        "external_id": external_id,
        "project": project,
        "status": status,
        "updated_at": updated_at,
        "final_result": final_result,
    }


def _reconciliation_text(dispositions: dict[str, str]) -> str:
    """The reconciliation-artifact line format this gate reads: a markdown
    bullet per row, `- <external_id> → <disposition>`. Mirrors the
    format `node_gates._RECONCILIATION_LINE` parses and the format the
    HOLD message's own enumeration lines use (`<external_id> →
    <statement>`) — one delimiter convention throughout."""
    lines = [f"- {eid} → {disposition}" for eid, disposition in dispositions.items()]
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# Unit level: node_gates.check_executing()
# ─────────────────────────────────────────────────────────────────────────────


class CheckExecutingTests(unittest.TestCase):
    """Every row here is disposed `done` in the reconciliation artifact —
    these tests are about the ORIGINAL (pre-D2) per-row verifier check,
    unaffected by disposition. The reconciliation layer itself gets its
    own coverage in `CheckExecutingReconciliationTests` below."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.verifications_dir = self.tmp_path / "verifications"
        self.verifications_dir.mkdir()
        self.workplan_path = self.tmp_path / "workplan.json"
        self.reconciliation_path = self.tmp_path / "reconciliation.md"

    def _write_workplan(self, project: str, external_ids: list[str]) -> None:
        self.workplan_path.write_text(
            json.dumps({
                "project": project,
                "work_items": [{"external_id": eid} for eid in external_ids],
            }),
            encoding="utf-8",
        )

    def _write_verification(self, name: str, data: dict[str, Any]) -> None:
        (self.verifications_dir / name).write_text(json.dumps(data), encoding="utf-8")

    def _write_all_done_reconciliation(self, external_ids: list[str]) -> None:
        self.reconciliation_path.write_text(
            _reconciliation_text({eid: "done" for eid in external_ids}), encoding="utf-8",
        )

    def _check(self) -> node_gates.GateResult:
        return node_gates.check_executing(self.workplan_path, self.verifications_dir, self.reconciliation_path)

    def test_empty_verifications_dir_refuses_naming_both_rows(self) -> None:
        self._write_workplan("proj", ["row-a", "row-b"])
        self._write_all_done_reconciliation(["row-a", "row-b"])

        result = self._check()

        self.assertFalse(result.ok)
        self.assertFalse(result.hold)
        joined = " ".join(result.messages)
        self.assertIn("row-a", joined)
        self.assertIn("row-b", joined)

    def test_one_done_one_unverifiable_holds(self) -> None:
        self._write_workplan("proj", ["row-a", "row-b"])
        self._write_all_done_reconciliation(["row-a", "row-b"])
        self._write_verification(
            "a.json",
            _verification(
                external_id="row-a", project="proj", status="done",
                updated_at="2026-09-06T00:00:00+00:00",
                outcome="done", readback_state="done",
            ),
        )
        self._write_verification(
            "b.json",
            _verification(
                external_id="row-b", project="proj", status="unverifiable",
                updated_at="2026-09-06T00:00:00+00:00", outcome="unverifiable",
            ),
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertTrue(result.hold)

    def test_all_done_passes(self) -> None:
        self._write_workplan("proj", ["row-a", "row-b"])
        self._write_all_done_reconciliation(["row-a", "row-b"])
        for name, eid in (("a.json", "row-a"), ("b.json", "row-b")):
            self._write_verification(
                name,
                _verification(
                    external_id=eid, project="proj", status="done",
                    updated_at="2026-09-06T00:00:00+00:00",
                    outcome="done", readback_state="done",
                ),
            )

        result = self._check()

        self.assertTrue(result.ok)
        self.assertFalse(result.hold)
        self.assertEqual([], result.messages)

    def test_already_done_outcome_also_passes(self) -> None:
        self._write_workplan("proj", ["row-a"])
        self._write_all_done_reconciliation(["row-a"])
        self._write_verification(
            "a.json",
            _verification(
                external_id="row-a", project="proj", status="done",
                updated_at="2026-09-06T00:00:00+00:00",
                outcome="already_done", readback_state="done",
            ),
        )

        result = self._check()

        self.assertTrue(result.ok)

    def test_two_files_for_one_row_newest_wins_pass(self) -> None:
        self._write_workplan("proj", ["row-a"])
        self._write_all_done_reconciliation(["row-a"])
        self._write_verification(
            "old.json",
            _verification(
                external_id="row-a", project="proj", status="unverifiable",
                updated_at="2026-09-06T00:00:00+00:00", outcome="unverifiable",
            ),
        )
        self._write_verification(
            "new.json",
            _verification(
                external_id="row-a", project="proj", status="done",
                updated_at="2026-09-07T00:00:00+00:00",
                outcome="done", readback_state="done",
            ),
        )

        result = self._check()

        self.assertTrue(result.ok, result.messages)

    def test_two_files_for_one_row_newest_wins_refuse(self) -> None:
        self._write_workplan("proj", ["row-a"])
        self._write_all_done_reconciliation(["row-a"])
        self._write_verification(
            "old.json",
            _verification(
                external_id="row-a", project="proj", status="done",
                updated_at="2026-09-06T00:00:00+00:00",
                outcome="done", readback_state="done",
            ),
        )
        self._write_verification(
            "new.json",
            _verification(
                external_id="row-a", project="proj", status="unverifiable",
                updated_at="2026-09-07T00:00:00+00:00", outcome="unverifiable",
            ),
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertTrue(result.hold)

    def test_newest_refused_refuses_not_hold(self) -> None:
        self._write_workplan("proj", ["row-a"])
        self._write_all_done_reconciliation(["row-a"])
        self._write_verification(
            "old.json",
            _verification(
                external_id="row-a", project="proj", status="done",
                updated_at="2026-09-06T00:00:00+00:00",
                outcome="done", readback_state="done",
            ),
        )
        self._write_verification(
            "new.json",
            _verification(
                external_id="row-a", project="proj", status="refused",
                updated_at="2026-09-07T00:00:00+00:00", outcome="refused",
            ),
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertFalse(result.hold)

    def test_refused_row_beats_unverifiable_row_no_hold(self) -> None:
        """Decision D reads 'no row is refused/missing AND >=1 unverifiable
        => HOLD'. One refused row alongside one unverifiable row must NOT
        hold — hold requires zero missing/refused rows."""
        self._write_workplan("proj", ["row-a", "row-b"])
        self._write_all_done_reconciliation(["row-a", "row-b"])
        self._write_verification(
            "a.json",
            _verification(
                external_id="row-a", project="proj", status="refused",
                updated_at="2026-09-06T00:00:00+00:00", outcome="refused",
            ),
        )
        self._write_verification(
            "b.json",
            _verification(
                external_id="row-b", project="proj", status="unverifiable",
                updated_at="2026-09-06T00:00:00+00:00", outcome="unverifiable",
            ),
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertFalse(result.hold)

    def test_unreadable_verification_file_is_skipped_not_fatal(self) -> None:
        self._write_workplan("proj", ["row-a"])
        self._write_all_done_reconciliation(["row-a"])
        (self.verifications_dir / "garbage.json").write_text("{not json", encoding="utf-8")
        self._write_verification(
            "a.json",
            _verification(
                external_id="row-a", project="proj", status="done",
                updated_at="2026-09-06T00:00:00+00:00",
                outcome="done", readback_state="done",
            ),
        )

        result = self._check()

        self.assertTrue(result.ok, result.messages)

    def test_missing_workplan_file_refuses_without_crash(self) -> None:
        """The workplan is read before the reconciliation artifact, so an
        unreadable/nonexistent reconciliation path (never touched) is fine
        here — this test is about the workplan-read failure alone."""
        result = node_gates.check_executing(
            self.tmp_path / "does-not-exist.json", self.verifications_dir, self.reconciliation_path,
        )

        self.assertFalse(result.ok)
        self.assertFalse(result.hold)
        self.assertTrue(result.messages)


class CheckExecutingReconciliationTests(unittest.TestCase):
    """The reconciliation gate itself (loop-ending-executing-live-done,
    2026-09-17): every workplan row must carry a disposition, `deferred`/
    `archived` pass without a verifier `done`, and `live-test` is the only
    disposition that may cross the gate open."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.verifications_dir = self.tmp_path / "verifications"
        self.verifications_dir.mkdir()
        self.workplan_path = self.tmp_path / "workplan.json"
        self.reconciliation_path = self.tmp_path / "reconciliation.md"

    def _write_workplan(self, project: str, external_ids: list[str]) -> None:
        self.workplan_path.write_text(
            json.dumps({
                "project": project,
                "work_items": [{"external_id": eid} for eid in external_ids],
            }),
            encoding="utf-8",
        )

    def _write_reconciliation(self, dispositions: dict[str, str]) -> None:
        self.reconciliation_path.write_text(_reconciliation_text(dispositions), encoding="utf-8")

    def _check(self) -> node_gates.GateResult:
        return node_gates.check_executing(self.workplan_path, self.verifications_dir, self.reconciliation_path)

    def test_row_missing_from_artifact_refuses_the_t53_hole(self) -> None:
        """The T5.3 hole this gate exists to close: a workplan row absent
        from the reconciliation artifact — it looked done and nobody
        actually closed it."""
        self._write_workplan("proj", ["row-a", "row-b"])
        self._write_reconciliation({"row-a": "done"})  # row-b never mentioned
        (self.verifications_dir / "a.json").write_text(
            json.dumps(_verification(
                external_id="row-a", project="proj", status="done",
                updated_at="2026-09-17T00:00:00+00:00", outcome="done", readback_state="done",
            )),
            encoding="utf-8",
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertFalse(result.hold)
        joined = " ".join(result.messages)
        self.assertIn("row-b", joined)
        self.assertIn("reconciliation artifact", joined)

    def test_reconciliation_artifact_absent_entirely_refuses_naming_the_file(self) -> None:
        self._write_workplan("proj", ["row-a"])
        # self.reconciliation_path is never written — it does not exist.

        result = self._check()

        self.assertFalse(result.ok)
        self.assertFalse(result.hold)
        self.assertIn(str(self.reconciliation_path), " ".join(result.messages))

    def test_deferred_and_archived_rows_pass_without_a_verifier_run(self) -> None:
        """No verifier run exists for either row at all — deferred and
        archived work was never built, so there is nothing to verify."""
        self._write_workplan("proj", ["row-a", "row-b"])
        self._write_reconciliation({"row-a": "deferred", "row-b": "archived"})

        result = self._check()

        self.assertTrue(result.ok, result.messages)
        self.assertFalse(result.hold)

    def test_live_test_row_passes_with_no_verifier_run(self) -> None:
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "live-test"})

        result = self._check()

        self.assertTrue(result.ok, result.messages)
        self.assertFalse(result.hold)

    def test_done_disposition_but_verifier_disagrees_refuses(self) -> None:
        """'done must agree with the verifier': the artifact cannot promote
        a row the verifier did not close. Here the row is missing a
        verifier run altogether — a straightforward disagreement."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        # No verifier run written for row-a at all.

        result = self._check()

        self.assertFalse(result.ok)
        self.assertFalse(result.hold)
        self.assertIn("row-a", " ".join(result.messages))

    def test_undischarged_built_work_manual_on_done_row_holds_and_names_it(self) -> None:
        """The feature this gate exists for: a `done`-disposed row whose
        only outstanding criterion is Daniel's own manual attestation
        HOLDs (never passes, never a hard refuse) — and the HOLD message
        enumerates `<external_id> → <the exact statement>` so an agent
        knows precisely which rows to walk Daniel through."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        (self.verifications_dir / "a.json").write_text(
            json.dumps(_unverifiable_with_landing(
                external_id="row-a", project="proj", updated_at="2026-09-17T00:00:00+00:00",
                verdicts=[
                    _verdict("file_state", discharged=True),
                    _verdict("manual", discharged=False, uncertain=True, statement="Daniel confirms X by eye."),
                ],
            )),
            encoding="utf-8",
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertTrue(result.hold)
        self.assertIn("row-a → Daniel confirms X by eye.", result.messages)

    def test_same_row_declared_live_test_passes(self) -> None:
        """The identical verifier evidence as the test above — the only
        thing that changes is the disposition — now passes outright,
        because `live-test` is exempt from the verifier check entirely."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "live-test"})
        (self.verifications_dir / "a.json").write_text(
            json.dumps(_unverifiable_with_landing(
                external_id="row-a", project="proj", updated_at="2026-09-17T00:00:00+00:00",
                verdicts=[
                    _verdict("file_state", discharged=True),
                    _verdict("manual", discharged=False, uncertain=True, statement="Daniel confirms X by eye."),
                ],
            )),
            encoding="utf-8",
        )

        result = self._check()

        self.assertTrue(result.ok, result.messages)
        self.assertFalse(result.hold)

    def test_all_done_plus_one_live_test_passes(self) -> None:
        self._write_workplan("proj", ["row-a", "row-b"])
        self._write_reconciliation({"row-a": "done", "row-b": "live-test"})
        (self.verifications_dir / "a.json").write_text(
            json.dumps(_verification(
                external_id="row-a", project="proj", status="done",
                updated_at="2026-09-17T00:00:00+00:00", outcome="done", readback_state="done",
            )),
            encoding="utf-8",
        )
        # row-b (live-test) carries no verifier run at all.

        result = self._check()

        self.assertTrue(result.ok, result.messages)
        self.assertFalse(result.hold)


# ─────────────────────────────────────────────────────────────────────────────
# Manual-only undischarged verdicts, reverted direction (loop-ending-
# executing-live-done, 2026-09-17): D2's manual-only-HOLD narrowing is
# REVERTED — Daniel: an undischarged `manual` criterion left unclosed is a
# failure to tell him built work was ready for review, not a free pass.
# Every positive ("passes") case D2 added now inverts to negative ("still
# HOLDs"); every negative-direction test D2 already carried is kept
# unchanged, now wired with a `done`-disposition reconciliation artifact.
# Real verification-file shape verified against live files under
# `node_gates.DEFAULT_VERIFICATIONS_DIR` this session — in particular run
# `96c4c071-cbae-48fb-a3dc-30421e2dfa0e` (external_id `ncf-m4-primer`, a
# genuine manual-only-uncertain row) and run
# `b506fa59-6a7f-41a3-9311-f2934b1e40a6` (external_id
# `ncf-m4-exit-gate-completion`, a `vet`-stage failure with no `landing`
# key at all — the shape `_landing_verdicts` must treat as "does not
# qualify", not crash on).
# ─────────────────────────────────────────────────────────────────────────────


def _verdict(
    kind: str, *, discharged: bool, failed: bool = False, uncertain: bool = False,
    statement: str = "a criterion",
) -> dict[str, Any]:
    return {
        "statement": statement,
        "kind": kind,
        "discharged": discharged,
        "failed": failed,
        "uncertain": uncertain,
        "evidence": "test evidence",
    }


def _unverifiable_with_landing(
    *, external_id: str, project: str, updated_at: str, verdicts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "external_id": external_id,
        "project": project,
        "status": "unverifiable",
        "updated_at": updated_at,
        "steps": {
            "landing": {"step": "landing", "status": "uncertain", "data": {"verdicts": verdicts}},
        },
        "final_result": {"outcome": "unverifiable"},
    }


def _unverifiable_vet_failure(*, external_id: str, project: str, updated_at: str) -> dict[str, Any]:
    """A real shape: `unverifiable` from a `vet`-stage failure that never
    reached `landing` — `steps` has no `landing` key at all (real example:
    run `b506fa59-6a7f-41a3-9311-f2934b1e40a6`, an unresolvable
    `acceptance_criteria_ref`)."""
    return {
        "external_id": external_id,
        "project": project,
        "status": "unverifiable",
        "updated_at": updated_at,
        "steps": {"vet": {"step": "vet", "status": "uncertain", "data": {}}},
        "final_result": {"outcome": "unverifiable"},
    }


class CheckExecutingManualOnlyHoldTests(unittest.TestCase):
    """Every row is disposed `done` — the disposition an agent gives real
    built work it believes is finished. `live-test` disposition tests
    live in `CheckExecutingReconciliationTests` above."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.verifications_dir = self.tmp_path / "verifications"
        self.verifications_dir.mkdir()
        self.workplan_path = self.tmp_path / "workplan.json"
        self.reconciliation_path = self.tmp_path / "reconciliation.md"

    def _write_workplan(self, project: str, external_ids: list[str]) -> None:
        self.workplan_path.write_text(
            json.dumps({
                "project": project,
                "work_items": [{"external_id": eid} for eid in external_ids],
            }),
            encoding="utf-8",
        )

    def _write_verification(self, name: str, data: dict[str, Any]) -> None:
        (self.verifications_dir / name).write_text(json.dumps(data), encoding="utf-8")

    def _write_all_done_reconciliation(self, external_ids: list[str]) -> None:
        self.reconciliation_path.write_text(
            _reconciliation_text({eid: "done" for eid in external_ids}), encoding="utf-8",
        )

    def _check(self) -> node_gates.GateResult:
        return node_gates.check_executing(self.workplan_path, self.verifications_dir, self.reconciliation_path)

    def test_only_manual_uncertain_still_holds(self) -> None:
        """The positive case D2 added — inverted. Every non-manual verdict
        discharged, the only uncertainty left is Daniel's own manual
        attestation, disposed `done` (not `live-test`): this must now HOLD,
        never pass, and the HOLD message must enumerate the exact
        statement so an agent knows what to walk Daniel through."""
        self._write_workplan("proj", ["row-a"])
        self._write_all_done_reconciliation(["row-a"])
        self._write_verification(
            "a.json",
            _unverifiable_with_landing(
                external_id="row-a", project="proj", updated_at="2026-09-17T00:00:00+00:00",
                verdicts=[
                    _verdict("file_state", discharged=True),
                    _verdict("manual", discharged=False, uncertain=True, statement="the manual criterion"),
                ],
            ),
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertTrue(result.hold)
        self.assertIn("row-a → the manual criterion", result.messages)

    def test_undischarged_command_check_still_holds(self) -> None:
        """An undischarged executable criterion (`command_check`) still
        HOLDs regardless of disposition — the reconciliation artifact
        cannot rescue an executable failure by declaring the row `done`."""
        self._write_workplan("proj", ["row-a"])
        self._write_all_done_reconciliation(["row-a"])
        self._write_verification(
            "a.json",
            _unverifiable_with_landing(
                external_id="row-a", project="proj", updated_at="2026-09-17T00:00:00+00:00",
                verdicts=[_verdict("command_check", discharged=False, uncertain=True)],
            ),
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertTrue(result.hold)

    def test_mixed_file_one_manual_one_executable_uncertain_still_holds(self) -> None:
        """One `manual` verdict uncertain alongside one executable verdict
        that is ALSO uncertain/undischarged — the row must still HOLD, not
        pass, and the manual criterion is still enumerated by name even
        though the row is not clean otherwise."""
        self._write_workplan("proj", ["row-a"])
        self._write_all_done_reconciliation(["row-a"])
        self._write_verification(
            "a.json",
            _unverifiable_with_landing(
                external_id="row-a", project="proj", updated_at="2026-09-17T00:00:00+00:00",
                verdicts=[
                    _verdict("manual", discharged=False, uncertain=True, statement="the manual criterion"),
                    _verdict("file_state", discharged=False, uncertain=True),
                ],
            ),
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertTrue(result.hold)
        self.assertIn("row-a → the manual criterion", result.messages)

    def test_failed_non_manual_verdict_still_holds_even_if_marked_discharged(self) -> None:
        """Defensive: a `failed: true` non-manual verdict never qualifies,
        regardless of its `discharged` value."""
        self._write_workplan("proj", ["row-a"])
        self._write_all_done_reconciliation(["row-a"])
        self._write_verification(
            "a.json",
            _unverifiable_with_landing(
                external_id="row-a", project="proj", updated_at="2026-09-17T00:00:00+00:00",
                verdicts=[
                    _verdict("file_state", discharged=True, failed=True),
                    _verdict("manual", discharged=False, uncertain=True),
                ],
            ),
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertTrue(result.hold)

    def test_vet_stage_failure_with_no_landing_key_still_holds(self) -> None:
        """A real shape: `unverifiable` from a `vet` failure that never
        reached `landing` at all. `_landing_verdicts` must return `None`
        (not crash), so the row falls through to the unchanged HOLD path —
        never a silent pass, and no enumeration line (there is nothing to
        enumerate)."""
        self._write_workplan("proj", ["row-a"])
        self._write_all_done_reconciliation(["row-a"])
        self._write_verification(
            "a.json",
            _unverifiable_vet_failure(
                external_id="row-a", project="proj", updated_at="2026-09-17T00:00:00+00:00",
            ),
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertTrue(result.hold)

    def test_refused_row_still_refuses_not_hold(self) -> None:
        """A `refused` row is a hard refusal, never a HOLD, regardless of
        the manual-verdict enumeration."""
        self._write_workplan("proj", ["row-a"])
        self._write_all_done_reconciliation(["row-a"])
        self._write_verification(
            "a.json",
            _verification(
                external_id="row-a", project="proj", status="refused",
                updated_at="2026-09-17T00:00:00+00:00", outcome="refused",
            ),
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertFalse(result.hold)

    def test_missing_row_still_refuses_not_hold(self) -> None:
        """No verifier run at all for the row is a hard refusal, never a
        HOLD."""
        self._write_workplan("proj", ["row-a"])
        self._write_all_done_reconciliation(["row-a"])

        result = self._check()

        self.assertFalse(result.ok)
        self.assertFalse(result.hold)
        self.assertIn("row-a", " ".join(result.messages))

    def test_mixed_workplan_one_done_one_manual_only_holds(self) -> None:
        """The positive mixed case D2 added — inverted. One genuinely
        `done` row alongside one manual-only-uncertain row, both disposed
        `done`: the overall gate result is now HOLD, not a pass, because
        the second row's manual criterion is still outstanding."""
        self._write_workplan("proj", ["row-a", "row-b"])
        self._write_all_done_reconciliation(["row-a", "row-b"])
        self._write_verification(
            "a.json",
            _verification(
                external_id="row-a", project="proj", status="done",
                updated_at="2026-09-17T00:00:00+00:00", outcome="done", readback_state="done",
            ),
        )
        self._write_verification(
            "b.json",
            _unverifiable_with_landing(
                external_id="row-b", project="proj", updated_at="2026-09-17T00:00:00+00:00",
                verdicts=[
                    _verdict("command_check", discharged=True),
                    _verdict("manual", discharged=False, uncertain=True, statement="the manual criterion"),
                ],
            ),
        )

        result = self._check()

        self.assertFalse(result.ok)
        self.assertTrue(result.hold)
        self.assertIn("row-b → the manual criterion", result.messages)


class GatePassExecutingManualOnlyHoldCLITests(unittest.TestCase):
    """CLI-level companion, reverted direction: `gate-pass --node executing`
    HOLDs (exit 3, state untouched) for a `done`-disposed workplan row
    whose only outstanding criterion is manual-only-uncertain — and passes
    (exit 0, confers `status: live` per D1) when that same row is instead
    declared `live-test`."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.workspace = self.tmp_path / "workspace"
        self.workspace.mkdir()
        self.input_path = self.tmp_path / "input.txt"
        self.input_path.write_text("Build the thing.\n", encoding="utf-8")
        self.verifications_dir = self.tmp_path / "verifications"
        self.verifications_dir.mkdir()
        self.workplan_path = self.tmp_path / "workplan.json"
        self.workplan_path.write_text(
            json.dumps({"project": "proj", "work_items": [{"external_id": "row-a"}]}),
            encoding="utf-8",
        )
        self.reconciliation_path = self.tmp_path / "reconciliation.md"
        (self.verifications_dir / "a.json").write_text(
            json.dumps(_unverifiable_with_landing(
                external_id="row-a", project="proj", updated_at="2026-09-17T00:00:00+00:00",
                verdicts=[
                    _verdict("file_state", discharged=True),
                    _verdict("manual", discharged=False, uncertain=True, statement="the manual criterion"),
                ],
            )),
            encoding="utf-8",
        )

        init_result = _run_cli(
            "init", "--goal", "demo-goal",
            "--input", str(self.input_path),
            "--workspace", str(self.workspace),
        )
        self.assertEqual(0, init_result.returncode, init_result.stdout + init_result.stderr)
        self.state_path = self.workspace / "demo-goal" / "loop.state.json"
        set_node_result = _run_cli("set-node", str(self.state_path), "--node", "executing")
        self.assertEqual(0, set_node_result.returncode, set_node_result.stdout + set_node_result.stderr)

    def _state_bytes(self) -> bytes:
        return self.state_path.read_bytes()

    def test_manual_only_uncertain_done_row_holds_exit_3_state_untouched(self) -> None:
        self.reconciliation_path.write_text(_reconciliation_text({"row-a": "done"}), encoding="utf-8")
        before = self._state_bytes()

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "executing", "--by", "test",
            "--artifact", str(self.input_path),
            "--workplan", str(self.workplan_path),
            "--verifications-dir", str(self.verifications_dir),
            "--reconciliation", str(self.reconciliation_path),
        )

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("row-a → the manual criterion", result.stderr)
        self.assertEqual(before, self._state_bytes())

    def test_same_row_declared_live_test_passes_exit_0_and_confers_live(self) -> None:
        self.reconciliation_path.write_text(_reconciliation_text({"row-a": "live-test"}), encoding="utf-8")

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "executing", "--by", "test",
            "--artifact", str(self.input_path),
            "--workplan", str(self.workplan_path),
            "--verifications-dir", str(self.verifications_dir),
            "--reconciliation", str(self.reconciliation_path),
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("live", payload["status"])
        self.assertEqual("executing", payload["current_node"])


# ─────────────────────────────────────────────────────────────────────────────
# CLI level: `loop_state.py gate-pass --node executing`
# ─────────────────────────────────────────────────────────────────────────────


class GatePassExecutingCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.workspace = self.tmp_path / "workspace"
        self.workspace.mkdir()
        self.input_path = self.tmp_path / "input.txt"
        self.input_path.write_text("Build the thing.\n", encoding="utf-8")
        self.verifications_dir = self.tmp_path / "verifications"
        self.verifications_dir.mkdir()
        self.workplan_path = self.tmp_path / "workplan.json"
        self.workplan_path.write_text(
            json.dumps({
                "project": "proj",
                "work_items": [{"external_id": "row-a"}, {"external_id": "row-b"}],
            }),
            encoding="utf-8",
        )
        self.reconciliation_path = self.tmp_path / "reconciliation.md"
        self.reconciliation_path.write_text(
            _reconciliation_text({"row-a": "done", "row-b": "done"}), encoding="utf-8",
        )

        init_result = _run_cli(
            "init", "--goal", "demo-goal",
            "--input", str(self.input_path),
            "--workspace", str(self.workspace),
        )
        self.assertEqual(0, init_result.returncode, init_result.stdout + init_result.stderr)
        self.state_path = self.workspace / "demo-goal" / "loop.state.json"

    def _state_hash(self) -> str:
        return hashlib.sha256(self.state_path.read_bytes()).hexdigest()

    def test_empty_verifications_dir_refuses_exit_1_state_unchanged(self) -> None:
        before_hash = self._state_hash()

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "executing", "--by", "test",
            "--artifact", str(self.input_path),
            "--workplan", str(self.workplan_path),
            "--verifications-dir", str(self.verifications_dir),
            "--reconciliation", str(self.reconciliation_path),
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("row-a", result.stderr)
        self.assertIn("row-b", result.stderr)
        combined = result.stdout + result.stderr
        for marker in PASS_MARKERS:
            self.assertNotIn(marker, combined)
        self.assertEqual(before_hash, self._state_hash())

    def test_one_done_one_unverifiable_holds_exit_3(self) -> None:
        (self.verifications_dir / "a.json").write_text(
            json.dumps(_verification(
                external_id="row-a", project="proj", status="done",
                updated_at="2026-09-06T00:00:00+00:00",
                outcome="done", readback_state="done",
            )),
            encoding="utf-8",
        )
        (self.verifications_dir / "b.json").write_text(
            json.dumps(_verification(
                external_id="row-b", project="proj", status="unverifiable",
                updated_at="2026-09-06T00:00:00+00:00", outcome="unverifiable",
            )),
            encoding="utf-8",
        )
        before_hash = self._state_hash()

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "executing", "--by", "test",
            "--artifact", str(self.input_path),
            "--workplan", str(self.workplan_path),
            "--verifications-dir", str(self.verifications_dir),
            "--reconciliation", str(self.reconciliation_path),
        )

        self.assertEqual(3, result.returncode)
        self.assertEqual(before_hash, self._state_hash())

    def test_all_done_passes_exit_0_and_freezes(self) -> None:
        for name, eid in (("a.json", "row-a"), ("b.json", "row-b")):
            (self.verifications_dir / name).write_text(
                json.dumps(_verification(
                    external_id=eid, project="proj", status="done",
                    updated_at="2026-09-06T00:00:00+00:00",
                    outcome="done", readback_state="done",
                )),
                encoding="utf-8",
            )

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "executing", "--by", "test",
            "--artifact", str(self.input_path),
            "--workplan", str(self.workplan_path),
            "--verifications-dir", str(self.verifications_dir),
            "--reconciliation", str(self.reconciliation_path),
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        gate_summaries = [{"node": g["node"], "passed": g["passed"]} for g in payload["gates"]]
        self.assertIn({"node": "executing", "passed": True}, gate_summaries)

    def test_all_done_plus_one_live_test_passes_exit_0_and_confers_live(self) -> None:
        """The required end-to-end shape: every row `done` and verified,
        plus exactly one row declared `live-test` with no verifier run at
        all — the whole gate still passes, exit 0, and the CLI-level
        readback shows `status: live`."""
        (self.verifications_dir / "a.json").write_text(
            json.dumps(_verification(
                external_id="row-a", project="proj", status="done",
                updated_at="2026-09-06T00:00:00+00:00",
                outcome="done", readback_state="done",
            )),
            encoding="utf-8",
        )
        # row-b carries no verifier run at all — it is the live test.
        self.reconciliation_path.write_text(
            _reconciliation_text({"row-a": "done", "row-b": "live-test"}), encoding="utf-8",
        )

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "executing", "--by", "test",
            "--artifact", str(self.input_path),
            "--workplan", str(self.workplan_path),
            "--verifications-dir", str(self.verifications_dir),
            "--reconciliation", str(self.reconciliation_path),
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("live", payload["status"])
        gate_summaries = [{"node": g["node"], "passed": g["passed"]} for g in payload["gates"]]
        self.assertIn({"node": "executing", "passed": True}, gate_summaries)

    def test_empty_artifact_list_refuses_exit_1(self) -> None:
        """D6a: a registered node's gate refuses an empty `--artifact` list
        outright — a Build exit that freezes nothing cannot record
        `passed: true`. All workplan rows read `done` here (copy of the
        passing setup in `test_all_done_passes_exit_0_and_freezes`) so the
        refusal is provably about the missing `--artifact`, not the
        verifier evidence."""
        for name, eid in (("a.json", "row-a"), ("b.json", "row-b")):
            (self.verifications_dir / name).write_text(
                json.dumps(_verification(
                    external_id=eid, project="proj", status="done",
                    updated_at="2026-09-06T00:00:00+00:00",
                    outcome="done", readback_state="done",
                )),
                encoding="utf-8",
            )
        before_hash = self._state_hash()

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "executing", "--by", "test",
            "--workplan", str(self.workplan_path),
            "--verifications-dir", str(self.verifications_dir),
            "--reconciliation", str(self.reconciliation_path),
        )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("artifact", result.stderr)
        combined = result.stdout + result.stderr
        for marker in PASS_MARKERS:
            self.assertNotIn(marker, combined)
        self.assertEqual(before_hash, self._state_hash())

    def test_missing_workplan_flag_is_usage_error_exit_2(self) -> None:
        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "executing", "--by", "test",
        )

        self.assertEqual(2, result.returncode)

    def test_missing_reconciliation_flag_is_usage_error_exit_2(self) -> None:
        """T4.9: `--reconciliation` is wired the same way `--workplan` is —
        supplying `--workplan` but not `--reconciliation` is provably the
        `--reconciliation` guard, not the `--workplan` one."""
        before_hash = self._state_hash()

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "executing", "--by", "test",
            "--artifact", str(self.input_path),
            "--workplan", str(self.workplan_path),
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("--reconciliation", result.stderr)
        self.assertEqual(before_hash, self._state_hash())

    def test_unregistered_node_is_refused_exit_2_and_freezes_nothing(self) -> None:
        """T4.8 final closure: D6's fail-open branch is DELETED. A node
        with no registered check (e.g. `verifying`) is now refused exit 2
        — checked FIRST, before the evidence-argument guards and before
        the empty-artifact guard, so nothing is loaded and nothing is
        frozen. Renamed from
        `test_unregistered_node_keeps_permissive_branch_exit_0` (moved off
        `specifying` when T4.5 registered it, D10) — this is that test's
        successor, not a new case."""
        before_hash = self._state_hash()

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "verifying", "--by", "test",
            "--artifact", str(self.input_path),
        )

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("no exit check is registered", result.stderr)
        self.assertEqual(before_hash, self._state_hash())


# ─────────────────────────────────────────────────────────────────────────────
# Adapter proof: the shipped fixture through GateBindingAdapter
# ─────────────────────────────────────────────────────────────────────────────


class BuildNoVerdictsFixtureAdapterTests(unittest.TestCase):
    def test_fixture_is_refused_by_the_gate_binding_adapter(self) -> None:
        case_path = FIXTURE_DIR / "case.json"
        raw = json.loads(case_path.read_text(encoding="utf-8"))
        fixture = loader.Fixture(path=case_path, raw=raw)
        context = AssertionContext(
            framework_root=HERE,
            repo_root=REPO_ROOT,
            verdicts_dir=HERE / "verdicts",
            traces_dir=HERE / "verdicts" / "traces",
        )

        evaluation = GateBindingAdapter().evaluate(fixture, 0, context)

        self.assertEqual("pass", evaluation.observation.outcome, evaluation.observation.detail)
        self.assertTrue(evaluation.observation.evidence.payload["refused"])
        self.assertEqual("pass", evaluation.checks[0].status)

    def test_state_file_untouched_by_the_fixture_run(self) -> None:
        state_path = FIXTURE_DIR / "loop.state.json"
        before = state_path.read_bytes()

        case_path = FIXTURE_DIR / "case.json"
        raw = json.loads(case_path.read_text(encoding="utf-8"))
        fixture = loader.Fixture(path=case_path, raw=raw)
        context = AssertionContext(
            framework_root=HERE,
            repo_root=REPO_ROOT,
            verdicts_dir=HERE / "verdicts",
            traces_dir=HERE / "verdicts" / "traces",
        )
        GateBindingAdapter().evaluate(fixture, 0, context)

        self.assertEqual(before, state_path.read_bytes())


# ═════════════════════════════════════════════════════════════════════════════
# T4.3 — Understand node (`understanding`): check_understanding(), the
# `gate-pass --tests` wiring, and the `understand-no-tests-file` fixture.
# ═════════════════════════════════════════════════════════════════════════════

#: A real N1 output in the exact envelope `check_understanding` consumes
#: (`CandidateWorkItem`; ledger ruling 2026-09-07). It predates the
#: `WHOLE-PATH:` marker and is never edited — tests mutate a copy.
EXEMPLAR_TESTS_JSON = (
    REPO_ROOT.parent / "AgentSecretBase" / "workspace"
    / "hyperspace-engine_new_sprintframework" / "01_understand" / "tests.json"
)
UNDERSTAND_FIXTURE_DIR = HERE / "fixtures" / "exit-gate" / "understand-no-tests-file"
WHOLE_PATH_PREFIX = "WHOLE-PATH: "
#: The C10 refusal LINE's prefix. The whole-path refusal also mentions
#: "PRD C10/C12", so a bare "C10" substring cannot tell the two apart.
C10_REFUSAL_PREFIX = "C10: no machine-checkable criterion"


def _strip_annotations(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_annotations(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_annotations(v) for v in obj]
    return obj


def _exemplar_payload() -> dict[str, Any]:
    """A fresh deep copy of the exemplar, annotations stripped, contract-valid
    but carrying NO whole-path marker (that is the exemplar's real state)."""
    return _strip_annotations(json.loads(EXEMPLAR_TESTS_JSON.read_text(encoding="utf-8")))


def _with_whole_path(payload: dict[str, Any], index: int = 0, prefix: str = WHOLE_PATH_PREFIX) -> dict[str, Any]:
    payload["acceptance_criteria"][index]["statement"] = (
        prefix + payload["acceptance_criteria"][index]["statement"]
    )
    return payload


def _all_manual(payload: dict[str, Any]) -> dict[str, Any]:
    for criterion in payload["acceptance_criteria"]:
        criterion["verification"] = {
            "kind": "manual",
            "instruction": "Daniel inspects the outcome and confirms it by eye.",
        }
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Unit level: node_gates.check_understanding()
# ─────────────────────────────────────────────────────────────────────────────


class CheckUnderstandingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.tests_path = self.tmp_path / "tests.json"

    def _write(self, payload: Any) -> Path:
        self.tests_path.write_text(json.dumps(payload), encoding="utf-8")
        return self.tests_path

    def _write_text(self, text: str) -> Path:
        self.tests_path.write_text(text, encoding="utf-8")
        return self.tests_path

    def _assert_refused(self, result: node_gates.GateResult, naming: str) -> None:
        self.assertFalse(result.ok)
        self.assertFalse(result.hold, "N1 has no HOLD path")
        self.assertIn(naming, " ".join(result.messages))

    def test_registered_in_checks_and_exported(self) -> None:
        self.assertIs(node_gates.CHECKS.get("understanding"), node_gates.check_understanding)
        self.assertIn("check_understanding", node_gates.__all__)

    def test_valid_passes_with_the_count_message(self) -> None:
        payload = _with_whole_path(_exemplar_payload())
        criteria = payload["acceptance_criteria"]
        executable = sum(1 for c in criteria if c["verification"]["kind"] != "manual")
        self.assertGreater(executable, 0)
        self.assertLess(executable, len(criteria), "exemplar carries at least one manual criterion")

        result = node_gates.check_understanding(self._write(payload))

        self.assertTrue(result.ok, result.messages)
        self.assertFalse(result.hold)
        self.assertEqual(
            [f"tests.json valid: {len(criteria)} criteria, {executable} executable, 1 whole-path"],
            result.messages,
        )

    def test_run_check_dispatches_understanding(self) -> None:
        payload = _with_whole_path(_exemplar_payload())

        result = node_gates.run_check("understanding", tests=self._write(payload))

        self.assertIsNotNone(result)
        self.assertTrue(result.ok, result.messages)

    def test_all_manual_refuses_naming_c10(self) -> None:
        """The whole-path marker is present so the refusal is provably C10,
        not the missing-marker cause."""
        payload = _all_manual(_with_whole_path(_exemplar_payload()))

        result = node_gates.check_understanding(self._write(payload))

        self._assert_refused(result, C10_REFUSAL_PREFIX)

    def test_no_whole_path_marker_refuses(self) -> None:
        """The unmodified exemplar: contract-valid, executable criteria
        present, no `WHOLE-PATH:` statement. The whole-path refusal text
        cites "PRD C10/C12" by design, so the negative assertion is on the
        C10 refusal LINE, not the bare token."""
        result = node_gates.check_understanding(self._write(_exemplar_payload()))

        self._assert_refused(result, "WHOLE-PATH:")
        self.assertNotIn(C10_REFUSAL_PREFIX, " ".join(result.messages))

    def test_marker_accepts_leading_whitespace_and_lowercase(self) -> None:
        payload = _with_whole_path(_exemplar_payload(), prefix="   whole-path: ")

        result = node_gates.check_understanding(self._write(payload))

        self.assertTrue(result.ok, result.messages)
        self.assertIn("1 whole-path", result.messages[0])

    def test_marker_must_lead_the_statement(self) -> None:
        payload = _with_whole_path(_exemplar_payload(), prefix="Exercise the WHOLE-PATH: ")

        result = node_gates.check_understanding(self._write(payload))

        self._assert_refused(result, "WHOLE-PATH:")

    def test_missing_file_refuses(self) -> None:
        missing = self.tmp_path / "does-not-exist.json"

        result = node_gates.check_understanding(missing)

        self._assert_refused(result, "unreadable/not JSON")
        self.assertIn(str(missing), " ".join(result.messages))

    def test_invalid_json_refuses(self) -> None:
        result = node_gates.check_understanding(self._write_text("{not json"))

        self._assert_refused(result, "unreadable/not JSON")

    def test_top_level_not_an_object_refuses(self) -> None:
        result = node_gates.check_understanding(self._write_text("[]"))

        self._assert_refused(result, "unreadable/not JSON")

    def test_contract_invalid_short_statement_refuses_with_contract_message(self) -> None:
        payload = _with_whole_path(_exemplar_payload())
        payload["acceptance_criteria"][1]["statement"] = "short"

        result = node_gates.check_understanding(self._write(payload))

        self._assert_refused(result, "acceptance_criteria.1.statement")
        self.assertIn("at least 10 characters", " ".join(result.messages))

    def test_contract_invalid_extra_field_refuses_with_contract_message(self) -> None:
        payload = _with_whole_path(_exemplar_payload())
        payload["bogus_field"] = 1

        result = node_gates.check_understanding(self._write(payload))

        self._assert_refused(result, "bogus_field")
        self.assertIn("Extra inputs are not permitted", " ".join(result.messages))

    def test_annotation_keys_are_stripped_at_every_depth(self) -> None:
        payload = _with_whole_path(_exemplar_payload())
        payload["_note"] = "top-level annotation"
        payload["specification"]["_note"] = "nested annotation"
        payload["acceptance_criteria"][0]["_note"] = "list-item annotation"

        result = node_gates.check_understanding(self._write(payload))

        self.assertTrue(result.ok, result.messages)


# ─────────────────────────────────────────────────────────────────────────────
# CLI level: `loop_state.py gate-pass --node understanding --tests PATH`
# ─────────────────────────────────────────────────────────────────────────────


class GatePassUnderstandingCLITests(unittest.TestCase):
    """Exit codes per the 2026-09-07 ledger ruling: 2 = `--node understanding`
    without `--tests`; 1 = refused (empty `--artifact` via the generic D6a
    guard, missing/unparseable/contract-invalid tests file, zero non-manual,
    zero `WHOLE-PATH:`); 0 = pass and freeze. No HOLD (3) path at N1."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.workspace = self.tmp_path / "workspace"
        self.workspace.mkdir()
        self.input_path = self.tmp_path / "input.txt"
        self.input_path.write_text("Understand the thing.\n", encoding="utf-8")
        self.problem_path = self.tmp_path / "Problem.md"
        self.problem_path.write_text("# Problem\n\nA real, short problem statement.\n", encoding="utf-8")
        self.valid_tests_path = self.tmp_path / "tests.json"
        self.valid_tests_path.write_text(
            json.dumps(_with_whole_path(_exemplar_payload())), encoding="utf-8"
        )

        init_result = _run_cli(
            "init", "--goal", "demo-goal",
            "--input", str(self.input_path),
            "--workspace", str(self.workspace),
        )
        self.assertEqual(0, init_result.returncode, init_result.stdout + init_result.stderr)
        self.state_path = self.workspace / "demo-goal" / "loop.state.json"
        set_node_result = _run_cli("set-node", str(self.state_path), "--node", "understanding")
        self.assertEqual(0, set_node_result.returncode, set_node_result.stdout + set_node_result.stderr)

    def _state_bytes(self) -> bytes:
        return self.state_path.read_bytes()

    def _assert_no_pass_marker(self, result: subprocess.CompletedProcess[str]) -> None:
        combined = result.stdout + result.stderr
        for marker in PASS_MARKERS:
            self.assertNotIn(marker, combined)

    def test_missing_tests_flag_is_usage_error_exit_2(self) -> None:
        """`--artifact` IS supplied so the exit is provably the `--tests`
        guard, not the D6a empty-artifact refusal."""
        before = self._state_bytes()

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "understanding", "--by", "test",
            "--artifact", str(self.problem_path),
        )

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("--tests", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_empty_artifact_list_refuses_exit_1(self) -> None:
        """D6a's generic guard now covers `understanding`: a VALID tests file
        is supplied so the refusal is provably about the missing artifact."""
        before = self._state_bytes()

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "understanding", "--by", "test",
            "--tests", str(self.valid_tests_path),
        )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("artifact", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_empty_artifact_message_is_node_neutral(self) -> None:
        """T4.8 D43: the empty-artifact refusal message is node-neutral —
        `understanding` is not a Build exit, so its refusal must not say
        "Build exit". A VALID tests file is supplied so the refusal is
        provably about the missing artifact, not the `--tests` guard."""
        before = self._state_bytes()

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "understanding", "--by", "test",
            "--tests", str(self.valid_tests_path),
        )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("an exit that freezes nothing", result.stderr)
        self.assertNotIn("Build exit", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_missing_tests_file_refuses_exit_1_state_byte_identical(self) -> None:
        before = self._state_bytes()
        missing = self.tmp_path / "missing.json"

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "understanding", "--by", "test",
            "--artifact", str(self.problem_path),
            "--tests", str(missing),
        )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("unreadable/not JSON", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_all_manual_file_refuses_exit_1_naming_c10(self) -> None:
        all_manual_path = self.tmp_path / "all-manual.json"
        all_manual_path.write_text(
            json.dumps(_all_manual(_with_whole_path(_exemplar_payload()))), encoding="utf-8"
        )
        before = self._state_bytes()

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "understanding", "--by", "test",
            "--artifact", str(self.problem_path),
            "--tests", str(all_manual_path),
        )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn(C10_REFUSAL_PREFIX, result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_valid_file_passes_exit_0_and_freezes_both_artifacts(self) -> None:
        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "understanding", "--by", "test",
            "--artifact", str(self.problem_path), str(self.valid_tests_path),
            "--tests", str(self.valid_tests_path),
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        frozen_paths = [artifact["path"] for artifact in payload["artifacts"]]
        self.assertIn(str(self.problem_path), frozen_paths)
        self.assertIn(str(self.valid_tests_path), frozen_paths)
        gate_summaries = [{"node": g["node"], "passed": g["passed"]} for g in payload["gates"]]
        self.assertIn({"node": "understanding", "passed": True}, gate_summaries)

    def test_contract_import_failure_refuses_exit_1_without_traceback(self) -> None:
        """Characterization test (written after the behaviour, passes on
        first run — not a TDD cycle): the fifth refusal cause in the ledger
        ruling. `AGENTOS_ROOT` pointed at an empty directory makes the live
        contract unimportable; the gate must refuse (exit 1) with the cause
        named, never crash, and freeze nothing."""
        empty_root = self.tmp_path / "empty-agentos"
        empty_root.mkdir()
        before = self._state_bytes()

        result = _run_cli(
            "gate-pass", str(self.state_path),
            "--node", "understanding", "--by", "test",
            "--artifact", str(self.problem_path),
            "--tests", str(self.valid_tests_path),
            env={**os.environ, "AGENTOS_ROOT": str(empty_root)},
        )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("cannot import the live CandidateWorkItem contract", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())


# ─────────────────────────────────────────────────────────────────────────────
# Adapter proof: the shipped `understand-no-tests-file` fixture through
# GateBindingAdapter (mirrors BuildNoVerdictsFixtureAdapterTests)
# ─────────────────────────────────────────────────────────────────────────────


class UnderstandNoTestsFileFixtureAdapterTests(unittest.TestCase):
    def _evaluate(self):
        case_path = UNDERSTAND_FIXTURE_DIR / "case.json"
        raw = json.loads(case_path.read_text(encoding="utf-8"))
        fixture = loader.Fixture(path=case_path, raw=raw)
        context = AssertionContext(
            framework_root=HERE,
            repo_root=REPO_ROOT,
            verdicts_dir=HERE / "verdicts",
            traces_dir=HERE / "verdicts" / "traces",
        )
        return GateBindingAdapter().evaluate(fixture, 0, context)

    def test_fixture_is_refused_by_the_gate_binding_adapter(self) -> None:
        evaluation = self._evaluate()

        self.assertEqual("pass", evaluation.observation.outcome, evaluation.observation.detail)
        self.assertTrue(evaluation.observation.evidence.payload["refused"])
        self.assertEqual("understand-gate-refusal", evaluation.observation.evidence.payload["error_class"])
        self.assertEqual("pass", evaluation.checks[0].status)

    def test_state_file_untouched_by_the_fixture_run(self) -> None:
        state_path = UNDERSTAND_FIXTURE_DIR / "loop.state.json"
        before = state_path.read_bytes()

        self._evaluate()

        self.assertEqual(before, state_path.read_bytes())

    def test_precondition_holds_missing_tests_file_absent_problem_present(self) -> None:
        """The refusal must be the check's ("unreadable/not JSON"), not the
        D6a empty-artifact guard's — so `Problem.md` exists and
        `missing.json` does not."""
        self.assertFalse((UNDERSTAND_FIXTURE_DIR / "missing.json").exists())
        self.assertTrue((UNDERSTAND_FIXTURE_DIR / "Problem.md").is_file())
        state = json.loads((UNDERSTAND_FIXTURE_DIR / "loop.state.json").read_text(encoding="utf-8"))
        self.assertEqual("understanding", state["current_node"])


# ═════════════════════════════════════════════════════════════════════════════
# T4.4 — Decide node (`deciding`): check_deciding(), the `gate-pass
# --decision` wiring, and the `decide-unmapped-component` fixture.
# ═════════════════════════════════════════════════════════════════════════════

#: A real frozen N1 output (4 criteria → `T1..T4`; `T4` is `manual`) — the
#: payload base for every N2 mapping test and the byte source of the
#: `decide-unmapped-component` fixture's `tests.json`. Read, never edited.
DECIDE_EXEMPLAR_TESTS_JSON = (
    REPO_ROOT.parent / "AgentSecretBase" / "workspace"
    / "hyperspace-engine_new_sprintframework" / "m4-loop" / "dogfood"
    / "t43-dogfood" / "01_understand" / "tests.json"
)
DECIDE_FIXTURE_DIR = HERE / "fixtures" / "exit-gate" / "decide-unmapped-component"
ALL_TEST_IDS = ["T1", "T2", "T3", "T4"]
LIVE_PRINCIPLE = "close-the-last-20-percent"
ARCHIVED_PRINCIPLE = "wer"
UNMAPPED_COMPONENT = "drift auto-repair script"

#: Two rows of the real `list_initiatives` return (ids verified live
#: 2026-09-07): one citable (`in-progress`), one not (`archived`).
PRINCIPLES_SNAPSHOT: dict[str, Any] = {
    "captured_at": "2026-09-07T11:00:00+00:00",
    "source": "mcp__nova-caelum-ops__list_initiatives",
    "initiatives": [
        {
            "id": "2b7439a2-2dad-46a8-90a3-0cf7a253513a",
            "external_id": LIVE_PRINCIPLE,
            "title": "Close the last 20% — ship to 100%, without letting a quick fix become a sprint",
            "state": "in-progress",
        },
        {
            "id": "f0cd9854-db9f-4785-95d4-4050f5247bd2",
            "external_id": ARCHIVED_PRINCIPLE,
            "title": "Test",
            "state": "archived",
        },
    ],
}

#: `## Deferred` bullets one name; `## Kept by principle` bullets another —
#: the check must read only the first section.
DEFERRED_MD = """# Deferred — demo

## Deferred

- **drift dashboard** — a live view of contract drift; no test names it, no principle keeps it.

## Kept by principle

- **single import root** — kept under close-the-last-20-percent.

## Overbloat review

- redundant: none.
"""


def _component(name: str, tests: list[str] | None = None, principles: list[str] | None = None) -> dict[str, Any]:
    return {"name": name, "tests": list(tests or []), "principles": list(principles or [])}


def _valid_components() -> list[dict[str, Any]]:
    """The brief's step-2 example minus its unmapped third component: one
    kept-by-test (all four ids), one kept-by-principle (a live id)."""
    return [
        _component("parity test file", ALL_TEST_IDS),
        _component("single import root", principles=[LIVE_PRINCIPLE]),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Unit level: node_gates.check_deciding()
# ─────────────────────────────────────────────────────────────────────────────


class CheckDecidingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Resolved up front: the check resolves `*_file` values against the
        # mapping's resolved parent, and macOS tempdirs live under a `/var`
        # → `/private/var` symlink — every expected path below must be in
        # the same form the check prints.
        self.tmp_path = Path(self._tmp.name).resolve()
        self.tests_path = self.tmp_path / "tests.json"
        self.tests_path.write_bytes(DECIDE_EXEMPLAR_TESTS_JSON.read_bytes())
        self.principles_path = self.tmp_path / "principles.json"
        self.principles_path.write_text(json.dumps(PRINCIPLES_SNAPSHOT), encoding="utf-8")
        self.deferred_path = self.tmp_path / "Deferred.md"
        self.deferred_path.write_text(DEFERRED_MD, encoding="utf-8")
        self.mapping_path = self.tmp_path / "mapping.json"

    def _mapping(self, components: list[Any], **overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "run": "demo",
            "tests_file": "tests.json",
            "deferred_file": "Deferred.md",
            "principles_file": "principles.json",
            "components": components,
        }
        data.update(overrides)
        return data

    def _write_mapping(self, data: Any, path: Path | None = None) -> Path:
        path = path or self.mapping_path
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def _check(self, components: list[Any], **overrides: Any) -> node_gates.GateResult:
        return node_gates.check_deciding(self._write_mapping(self._mapping(components, **overrides)))

    def _assert_refused(self, result: node_gates.GateResult, naming: str) -> None:
        self.assertFalse(result.ok)
        self.assertFalse(result.hold, "N2 has no HOLD path")
        self.assertIn(naming, " ".join(result.messages))

    def test_registered_in_checks_in_node_order_and_exported(self) -> None:
        self.assertIs(node_gates.CHECKS.get("deciding"), node_gates.check_deciding)
        self.assertEqual(["understanding", "deciding", "specifying", "executing"], list(node_gates.CHECKS))  # T4.5 registered specifying (D10)
        self.assertIn("check_deciding", node_gates.__all__)

    def test_valid_all_four_tests_mapped_passes_with_the_count_message(self) -> None:
        result = self._check(_valid_components())

        self.assertTrue(result.ok, result.messages)
        self.assertFalse(result.hold)
        self.assertEqual(
            ["mapping valid: 4 tests, 2 components (1 kept-by-test, 1 kept-by-principle, 0 deferred)"],
            result.messages,
        )

    def test_run_check_dispatches_deciding(self) -> None:
        path = self._write_mapping(self._mapping(_valid_components()))

        result = node_gates.run_check("deciding", decision=path)

        self.assertIsNotNone(result)
        self.assertTrue(result.ok, result.messages)

    def test_unmapped_component_not_deferred_refuses_naming_component_and_deferred_path(self) -> None:
        result = self._check([*_valid_components(), _component(UNMAPPED_COMPONENT)])

        self._assert_refused(
            result,
            f"{UNMAPPED_COMPONENT}: unmapped — no test, no principle, and not named under "
            f"## Deferred in {self.deferred_path}",
        )

    def test_unmapped_component_bulleted_under_deferred_passes_counting_it(self) -> None:
        result = self._check([*_valid_components(), _component("drift dashboard")])

        self.assertTrue(result.ok, result.messages)
        self.assertEqual(
            ["mapping valid: 4 tests, 3 components (1 kept-by-test, 1 kept-by-principle, 1 deferred)"],
            result.messages,
        )

    def test_name_bulleted_only_under_kept_by_principle_is_not_deferred(self) -> None:
        """Section-scoped: `single import root` is bold-bulleted under
        `## Kept by principle`, never under `## Deferred`."""
        result = self._check([_component("parity test file", ALL_TEST_IDS), _component("single import root")])

        self._assert_refused(result, "single import root: unmapped")

    def test_deferred_bullet_accepts_star_marker_and_indent(self) -> None:
        self.deferred_path.write_text("## Deferred\n\n  *   **drift dashboard** — cut.\n", encoding="utf-8")

        result = self._check([*_valid_components(), _component("drift dashboard")])

        self.assertTrue(result.ok, result.messages)
        self.assertIn("1 deferred", result.messages[0])

    def test_deferred_file_without_a_deferred_section_yields_empty_set(self) -> None:
        self.deferred_path.write_text("# Deferred\n\n## Kept by principle\n\n- **drift dashboard** — kept.\n", encoding="utf-8")

        result = self._check([*_valid_components(), _component("drift dashboard")])

        self._assert_refused(result, "drift dashboard: unmapped")

    def test_test_with_no_component_refuses_naming_the_id(self) -> None:
        components = [_component("parity test file", ["T1", "T2", "T4"]), _component("single import root", principles=[LIVE_PRINCIPLE])]

        result = self._check(components)

        self._assert_refused(result, "T3 maps to no component")
        self.assertEqual(["T3 maps to no component"], result.messages)

    def test_unknown_test_id_refuses_naming_the_declared_range(self) -> None:
        for bad in ("T9", "T0", "t1", "T01", "T", "1"):
            with self.subTest(bad=bad):
                components = [_component("parity test file", [*ALL_TEST_IDS, bad]), _component("single import root", principles=[LIVE_PRINCIPLE])]

                result = self._check(components)

                self._assert_refused(result, f"parity test file: unknown test id {bad} (tests.json declares T1..T4)")

    def test_unknown_principle_refuses(self) -> None:
        components = [_component("parity test file", ALL_TEST_IDS), _component("single import root", principles=["no-such-principle"])]

        result = self._check(components)

        self._assert_refused(result, "single import root: unknown principle no-such-principle — not in principles.json")

    def test_archived_principle_refuses_naming_the_state(self) -> None:
        components = [_component("parity test file", ALL_TEST_IDS), _component("single import root", principles=[ARCHIVED_PRINCIPLE])]

        result = self._check(components)

        self._assert_refused(
            result,
            f"single import root: principle {ARCHIVED_PRINCIPLE} is archived — not a declared principle (planned/in-progress/paused)",
        )

    def test_every_citable_state_keeps_a_component_by_principle(self) -> None:
        for state in ("planned", "in-progress", "paused"):
            with self.subTest(state=state):
                snapshot = {**PRINCIPLES_SNAPSHOT, "initiatives": [{"id": "x", "external_id": "p", "title": "P", "state": state}]}
                self.principles_path.write_text(json.dumps(snapshot), encoding="utf-8")

                result = self._check([_component("parity test file", ALL_TEST_IDS), _component("single import root", principles=["p"])])

                self.assertTrue(result.ok, result.messages)
                self.assertIn("1 kept-by-principle", result.messages[0])

    def test_empty_initiatives_list_is_legal(self) -> None:
        self.principles_path.write_text(json.dumps({**PRINCIPLES_SNAPSHOT, "initiatives": []}), encoding="utf-8")

        result = self._check([_component("parity test file", ALL_TEST_IDS)])

        self.assertTrue(result.ok, result.messages)
        self.assertEqual(["mapping valid: 4 tests, 1 components (1 kept-by-test, 0 kept-by-principle, 0 deferred)"], result.messages)

    def test_missing_mapping_file_refuses_naming_the_path_as_given(self) -> None:
        missing = self.tmp_path / "does-not-exist.json"

        result = node_gates.check_deciding(missing)

        self._assert_refused(result, f"mapping file unreadable/not JSON: {missing}")

    def test_mapping_not_json_or_not_an_object_refuses(self) -> None:
        for text in ("{not json", "[]", "42"):
            with self.subTest(text=text):
                self.mapping_path.write_text(text, encoding="utf-8")

                result = node_gates.check_deciding(self.mapping_path)

                self._assert_refused(result, f"mapping file unreadable/not JSON: {self.mapping_path}")

    def test_missing_tests_file_refuses_with_resolved_path(self) -> None:
        result = self._check(_valid_components(), tests_file="nope/tests.json")

        self._assert_refused(result, f"tests file unreadable/not JSON: {self.tmp_path / 'nope' / 'tests.json'}")

    def test_tests_file_with_no_acceptance_criteria_refuses(self) -> None:
        for payload in ({}, {"acceptance_criteria": []}, {"acceptance_criteria": "T1"}):
            with self.subTest(payload=payload):
                self.tests_path.write_text(json.dumps(payload), encoding="utf-8")

                result = self._check(_valid_components())

                self._assert_refused(result, f"tests file declares no acceptance_criteria: {self.tests_path}")

    def test_missing_principles_file_refuses_with_resolved_path(self) -> None:
        result = self._check(_valid_components(), principles_file="nope/principles.json")

        self._assert_refused(result, f"principles file unreadable/not JSON: {self.tmp_path / 'nope' / 'principles.json'}")

    def test_principles_file_with_no_initiatives_list_refuses(self) -> None:
        for payload in ({}, {"initiatives": {"a": 1}}):
            with self.subTest(payload=payload):
                self.principles_path.write_text(json.dumps(payload), encoding="utf-8")

                result = self._check(_valid_components())

                self._assert_refused(result, f"principles file declares no initiatives list: {self.principles_path}")

    def test_missing_deferred_file_refuses_with_resolved_path(self) -> None:
        result = self._check(_valid_components(), deferred_file="nope/Deferred.md")

        self._assert_refused(result, f"deferred file unreadable: {self.tmp_path / 'nope' / 'Deferred.md'}")

    def test_missing_key_refuses_naming_the_key(self) -> None:
        for key in ("tests_file", "deferred_file", "principles_file", "components"):
            with self.subTest(key=key):
                data = self._mapping(_valid_components())
                del data[key]

                result = node_gates.check_deciding(self._write_mapping(data))

                self._assert_refused(result, f"mapping missing key: {key}")

    def test_components_not_a_list_refuses_as_missing_key(self) -> None:
        result = self._check({"name": "parity test file"})  # type: ignore[arg-type]

        self._assert_refused(result, "mapping missing key: components")

    def test_empty_components_refuses(self) -> None:
        result = self._check([])

        self._assert_refused(result, "mapping names no components")

    def test_component_without_a_name_refuses(self) -> None:
        for bad in ({"tests": ALL_TEST_IDS}, {"name": ""}, {"name": 3}, "parity test file"):
            with self.subTest(bad=bad):
                result = self._check([bad, _component("single import root", ALL_TEST_IDS)])

                self._assert_refused(result, "component has no name")

    def test_duplicate_component_name_refuses(self) -> None:
        result = self._check([_component("parity test file", ALL_TEST_IDS), _component("parity test file", principles=[LIVE_PRINCIPLE])])

        self._assert_refused(result, "duplicate component name: parity test file")

    def test_file_paths_resolve_relative_to_the_mapping_files_parent(self) -> None:
        sub = self.tmp_path / "02_decide"
        sub.mkdir()
        data = self._mapping(
            _valid_components(),
            tests_file="../tests.json", deferred_file="../Deferred.md", principles_file="../principles.json",
        )

        result = node_gates.check_deciding(self._write_mapping(data, sub / "mapping.json"))

        self.assertTrue(result.ok, result.messages)

    def test_absolute_file_paths_are_used_as_is(self) -> None:
        sub = self.tmp_path / "02_decide"
        sub.mkdir()
        data = self._mapping(
            _valid_components(),
            tests_file=str(self.tests_path), deferred_file=str(self.deferred_path), principles_file=str(self.principles_path),
        )

        result = node_gates.check_deciding(self._write_mapping(data, sub / "mapping.json"))

        self.assertTrue(result.ok, result.messages)

    def test_multiple_refusals_in_one_run_are_all_collected(self) -> None:
        """The driver fixes them in one pass: an unknown test id, an unknown
        principle, an unmapped component and two tests with no component,
        all from a single call."""
        components = [
            _component("parity test file", ["T1", "T2", "T9"]),
            _component("single import root", principles=["no-such-principle"]),
            _component(UNMAPPED_COMPONENT),
        ]

        result = self._check(components)

        self.assertFalse(result.ok)
        self.assertFalse(result.hold)
        self.assertEqual(
            [
                "parity test file: unknown test id T9 (tests.json declares T1..T4)",
                "single import root: unknown principle no-such-principle — not in principles.json",
                f"{UNMAPPED_COMPONENT}: unmapped — no test, no principle, and not named under ## Deferred in {self.deferred_path}",
                "T3 maps to no component",
                "T4 maps to no component",
            ],
            result.messages,
        )


# ─────────────────────────────────────────────────────────────────────────────
# CLI level: `loop_state.py gate-pass --node deciding --decision PATH`
# ─────────────────────────────────────────────────────────────────────────────


class GatePassDecidingCLITests(unittest.TestCase):
    """Exit codes mirror `understanding` (D23): 2 = `--node deciding` without
    `--decision`; 1 = refused (empty `--artifact` via the generic D6a guard,
    missing/unparseable mapping, any mapping refusal); 0 = pass and freeze.
    No HOLD (3) path at N2. Scratch state reaches `deciding` by the legal
    path `init` → `set-node understanding` → `set-node deciding`."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name).resolve()
        self.workspace = self.tmp_path / "workspace"
        self.workspace.mkdir()
        self.input_path = self.tmp_path / "input.txt"
        self.input_path.write_text("Decide the thing.\n", encoding="utf-8")

        # A run-shaped layout: N1's tests.json one directory up from N2's
        # artifacts, so the mapping's `../01_understand/tests.json` is real.
        self.tests_path = self.tmp_path / "01_understand" / "tests.json"
        self.tests_path.parent.mkdir()
        self.tests_path.write_bytes(DECIDE_EXEMPLAR_TESTS_JSON.read_bytes())
        self.decide_dir = self.tmp_path / "02_decide"
        self.decide_dir.mkdir()
        self.decision_path = self.decide_dir / "Decision.md"
        self.decision_path.write_text("# Decision\n\n## Options\n\nA real, short decision.\n", encoding="utf-8")
        self.deferred_path = self.decide_dir / "Deferred.md"
        self.deferred_path.write_text(DEFERRED_MD, encoding="utf-8")
        self.principles_path = self.decide_dir / "principles.json"
        self.principles_path.write_text(json.dumps(PRINCIPLES_SNAPSHOT), encoding="utf-8")
        self.mapping_path = self.decide_dir / "mapping.json"
        self._write_mapping(_valid_components())

        init_result = _run_cli(
            "init", "--goal", "demo-goal",
            "--input", str(self.input_path),
            "--workspace", str(self.workspace),
        )
        self.assertEqual(0, init_result.returncode, init_result.stdout + init_result.stderr)
        self.state_path = self.workspace / "demo-goal" / "loop.state.json"
        for node in ("understanding", "deciding"):
            set_node_result = _run_cli("set-node", str(self.state_path), "--node", node)
            self.assertEqual(0, set_node_result.returncode, set_node_result.stdout + set_node_result.stderr)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual("deciding", state["current_node"])

    def _write_mapping(self, components: list[dict[str, Any]]) -> None:
        self.mapping_path.write_text(
            json.dumps({
                "run": "demo-goal",
                "tests_file": "../01_understand/tests.json",
                "deferred_file": "Deferred.md",
                "principles_file": "principles.json",
                "components": components,
            }),
            encoding="utf-8",
        )

    def _gate_pass(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return _run_cli("gate-pass", str(self.state_path), "--node", "deciding", "--by", "test", *extra)

    def _state_bytes(self) -> bytes:
        return self.state_path.read_bytes()

    def _assert_no_pass_marker(self, result: subprocess.CompletedProcess[str]) -> None:
        combined = result.stdout + result.stderr
        for marker in PASS_MARKERS:
            self.assertNotIn(marker, combined)

    def test_missing_decision_flag_is_usage_error_exit_2(self) -> None:
        """`--artifact` IS supplied so the exit is provably the `--decision`
        guard, not the D6a empty-artifact refusal."""
        before = self._state_bytes()

        result = self._gate_pass("--artifact", str(self.decision_path), str(self.deferred_path))

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("gate-pass --node deciding requires --decision PATH (T4.4)", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_empty_artifact_list_refuses_exit_1(self) -> None:
        """D6a's generic guard covers `deciding`: a VALID mapping is supplied
        so the refusal is provably about the missing artifact."""
        before = self._state_bytes()

        result = self._gate_pass("--decision", str(self.mapping_path))

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("artifact", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_missing_mapping_file_refuses_exit_1_state_byte_identical(self) -> None:
        before = self._state_bytes()
        missing = self.decide_dir / "missing.json"

        result = self._gate_pass(
            "--artifact", str(self.decision_path), str(self.deferred_path),
            "--decision", str(missing),
        )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn(f"mapping file unreadable/not JSON: {missing}", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_unmapped_component_refuses_exit_1_naming_the_component(self) -> None:
        self._write_mapping([*_valid_components(), _component(UNMAPPED_COMPONENT)])
        before = self._state_bytes()

        result = self._gate_pass(
            "--artifact", str(self.decision_path), str(self.deferred_path),
            "--decision", str(self.mapping_path),
        )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn(f"{UNMAPPED_COMPONENT}: unmapped", result.stderr)
        self.assertIn(f"## Deferred in {self.deferred_path}", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_valid_mapping_passes_exit_0_and_freezes_all_four_artifacts(self) -> None:
        artifacts = [self.decision_path, self.deferred_path, self.mapping_path, self.principles_path]

        result = self._gate_pass(
            "--artifact", *(str(path) for path in artifacts),
            "--decision", str(self.mapping_path),
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        frozen_paths = [artifact["path"] for artifact in payload["artifacts"]]
        for path in artifacts:
            self.assertIn(str(path), frozen_paths)
        gate_summaries = [{"node": g["node"], "passed": g["passed"]} for g in payload["gates"]]
        self.assertIn({"node": "deciding", "passed": True}, gate_summaries)


# ─────────────────────────────────────────────────────────────────────────────
# Adapter proof: the shipped `decide-unmapped-component` fixture through
# GateBindingAdapter (mirrors UnderstandNoTestsFileFixtureAdapterTests)
# ─────────────────────────────────────────────────────────────────────────────


class DecideUnmappedComponentFixtureAdapterTests(unittest.TestCase):
    def _context(self) -> AssertionContext:
        return AssertionContext(
            framework_root=HERE,
            repo_root=REPO_ROOT,
            verdicts_dir=HERE / "verdicts",
            traces_dir=HERE / "verdicts" / "traces",
        )

    def _evaluate(self):
        case_path = DECIDE_FIXTURE_DIR / "case.json"
        raw = json.loads(case_path.read_text(encoding="utf-8"))
        fixture = loader.Fixture(path=case_path, raw=raw)
        return GateBindingAdapter().evaluate(fixture, 0, self._context())

    def _gate_arguments(self) -> list[str]:
        """`gate.json`'s arguments with `{fixture_dir}` rendered exactly as
        the adapter renders it (`assertions/gate_binding.py`)."""
        descriptor = json.loads((DECIDE_FIXTURE_DIR / "gate.json").read_text(encoding="utf-8"))
        return [
            str(value).replace("{fixture_dir}", str(DECIDE_FIXTURE_DIR.resolve()))
            for value in descriptor["arguments"]
        ]

    def test_fixture_is_refused_by_the_gate_binding_adapter(self) -> None:
        evaluation = self._evaluate()

        self.assertEqual("pass", evaluation.observation.outcome, evaluation.observation.detail)
        self.assertTrue(evaluation.observation.evidence.payload["refused"])
        self.assertEqual("decide-gate-refusal", evaluation.observation.evidence.payload["error_class"])
        self.assertEqual("pass", evaluation.checks[0].status)

    def test_gate_arguments_run_directly_name_the_unmapped_component(self) -> None:
        """The adapter reports only exit + marker; the refusal TEXT is
        asserted by running `gate.json`'s exact arguments through the CLI."""
        state_path = DECIDE_FIXTURE_DIR / "loop.state.json"
        before = state_path.read_bytes()

        result = _run_cli(*self._gate_arguments())

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn(f"{UNMAPPED_COMPONENT}: unmapped", result.stderr)
        self.assertIn("## Deferred in", result.stderr)
        combined = result.stdout + result.stderr
        for marker in PASS_MARKERS:
            self.assertNotIn(marker, combined)
        self.assertEqual(before, state_path.read_bytes())

    def test_state_file_untouched_by_the_fixture_run(self) -> None:
        state_path = DECIDE_FIXTURE_DIR / "loop.state.json"
        before = state_path.read_bytes()

        self._evaluate()

        self.assertEqual(before, state_path.read_bytes())

    def test_precondition_holds_unmapped_component_undeclared_artifacts_present(self) -> None:
        """The refusal must be the check's (`unmapped`), not the D6a
        empty-artifact guard's — so `Decision.md` and `Deferred.md` exist,
        the third component maps to nothing, and `## Deferred` bullets
        some OTHER name."""
        mapping = json.loads((DECIDE_FIXTURE_DIR / "mapping.json").read_text(encoding="utf-8"))
        unmapped = [c for c in mapping["components"] if c["name"] == UNMAPPED_COMPONENT]
        self.assertEqual(1, len(unmapped))
        self.assertEqual([], unmapped[0]["tests"])
        self.assertEqual([], unmapped[0]["principles"])
        self.assertEqual("tests.json", mapping["tests_file"])

        deferred = node_gates._deferred_names((DECIDE_FIXTURE_DIR / "Deferred.md").read_text(encoding="utf-8"))
        self.assertNotIn(UNMAPPED_COMPONENT, deferred)
        self.assertTrue(deferred, "## Deferred must bullet at least one other name")

        for name in ("Decision.md", "Deferred.md", "principles.json", "original_input.md"):
            self.assertTrue((DECIDE_FIXTURE_DIR / name).is_file(), name)
        self.assertEqual(
            DECIDE_EXEMPLAR_TESTS_JSON.read_bytes(),
            (DECIDE_FIXTURE_DIR / "tests.json").read_bytes(),
            "fixture tests.json must be a byte copy of the t43 dogfood's frozen N1 output",
        )
        state = json.loads((DECIDE_FIXTURE_DIR / "loop.state.json").read_text(encoding="utf-8"))
        self.assertEqual("deciding", state["current_node"])


# ═════════════════════════════════════════════════════════════════════════════
# T4.5 — Draft node (`specifying`): check_specifying(), the `gate-pass
# --plan` wiring, and the `draft-blank-task-id` fixture.
# ═════════════════════════════════════════════════════════════════════════════

#: The REAL live Plan of this run — 47 `#### T` blocks under 7 `## M` modules,
#: every `task_id` backfilled; L684 is the annotated form `<uuid> *(backfilled
#: 2026-09-06 from the live row)*`. A frozen artifact: read, never edited.
LIVE_PLAN = (
    REPO_ROOT.parent / "AgentSecretBase" / "workspace"
    / "hyperspace-engine_new_sprintframework" / "Plan_NovaCaelumFramework_ChiefPM_2026-08-27.md"
)
DRAFT_FIXTURE_DIR = HERE / "fixtures" / "exit-gate" / "draft-blank-task-id"
UUID_1 = "11476bcf-5e84-439f-b823-e168656ceab2"
UUID_2 = "a94d8d31-e887-4d1c-8135-0b800287fbd3"
UUID_3 = "903b66a4-9fca-4f63-b143-d8908f498a51"
BACKFILL_ANNOTATION = " *(backfilled 2026-09-06 from the live row)*"
BLANK_TASK_ID_MESSAGE = "task_id is blank — not backfilled by the uploader"
NOT_UUID_MESSAGE = "is not a UUID — not backfilled by the uploader"
NO_TASK_ID_FIELD_MESSAGE = "no task_id field"
ZERO_BLOCKS_MESSAGE = "plan declares no task blocks (no level-4 #### T<n>.<m> heading)"

#: Header lines plus ONE module block in the live Plan's shape — the module
#: carries its own `**external_id:**` line and no `task_id`, and must
#: contribute nothing to the check.
PLAN_PREAMBLE = """# Plan — demo

**Project code:** `graph-machine-testbed`
**Companion PRD:** `PRD.md`
**External-id namespace:** `fx-`

## M1 — Contract parity

**external_id:** `fx-m1-parity`
**Owner:** engineer
**Summary:** Keep the two contract copies from drifting apart without anyone noticing.
**Acceptance criteria:** every task below is done and the parity test runs inside the suite line.
**Blocked by:** nothing
"""


def _task_id_line(value: str) -> str:
    return f"- **task_id:** {value}"


def _task_block(label: str, external_id: str, task_id_line: str | None) -> str:
    """One `#### T<n>.<m>` block in the live Plan's shape: the `task_id`
    marker first (absent when `task_id_line` is None), then `external_id`,
    then a few more field markers — enough to resemble the real thing."""
    lines = [f"#### {label} — A task about contract parity", ""]
    if task_id_line is not None:
        lines.append(task_id_line)
    lines += [
        f"- **external_id:** `{external_id}`",
        "- **Owner:** engineer",
        "- **Summary:** One small, plain-English step toward contract parity.",
        "- **Path:** `system/tests_library/framework/`",
        "",
    ]
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# Unit level: node_gates.check_specifying()
# ─────────────────────────────────────────────────────────────────────────────


class CheckSpecifyingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.plan_path = self.tmp_path / "Plan.md"

    def _write(self, text: str) -> Path:
        self.plan_path.write_text(text, encoding="utf-8")
        return self.plan_path

    def _plan(self, *blocks: str) -> Path:
        return self._write(PLAN_PREAMBLE + "\n" + "".join(blocks))

    def _assert_refused(self, result: node_gates.GateResult, naming: str) -> None:
        self.assertFalse(result.ok)
        self.assertFalse(result.hold, "N3 has no HOLD path")
        self.assertIn(naming, " ".join(result.messages))

    def test_registered_in_checks_in_node_order_and_exported(self) -> None:
        self.assertIs(node_gates.CHECKS.get("specifying"), node_gates.check_specifying)
        self.assertEqual(["understanding", "deciding", "specifying", "executing"], list(node_gates.CHECKS))
        self.assertIn("check_specifying", node_gates.__all__)

    def test_two_blocks_with_plain_uuids_pass_with_the_count_message(self) -> None:
        plan = self._plan(
            _task_block("T1.1", "fx-t11-parity-test", _task_id_line(UUID_1)),
            _task_block("T1.2", "fx-t12-suite-registration", _task_id_line(UUID_2)),
        )

        result = node_gates.check_specifying(plan)

        self.assertTrue(result.ok, result.messages)
        self.assertFalse(result.hold)
        self.assertEqual(["plan valid: 2 task blocks, all task_ids backfilled"], result.messages)

    def test_run_check_dispatches_specifying(self) -> None:
        plan = self._plan(_task_block("T1.1", "fx-t11-parity-test", _task_id_line(UUID_1)))

        result = node_gates.run_check("specifying", plan=plan)

        self.assertIsNotNone(result)
        self.assertTrue(result.ok, result.messages)

    def test_annotated_backfilled_form_passes(self) -> None:
        """The live Plan's L684 shape: `<uuid> *(backfilled 2026-09-06 from
        the live row)*` — an exact-UUID regex would refuse it; only the
        first whitespace-delimited token is matched."""
        plan = self._plan(_task_block("T1.1", "fx-t11-parity-test", _task_id_line(UUID_1 + BACKFILL_ANNOTATION)))

        result = node_gates.check_specifying(plan)

        self.assertTrue(result.ok, result.messages)
        self.assertEqual(["plan valid: 1 task blocks, all task_ids backfilled"], result.messages)

    def test_backticked_uuid_passes(self) -> None:
        plan = self._plan(_task_block("T1.1", "fx-t11-parity-test", _task_id_line(f"`{UUID_1}`")))

        result = node_gates.check_specifying(plan)

        self.assertTrue(result.ok, result.messages)

    def test_empty_value_refuses_naming_the_label_with_the_blank_message(self) -> None:
        plan = self._plan(_task_block("T1.1", "fx-t11-parity-test", "- **task_id:** "))

        result = node_gates.check_specifying(plan)

        self._assert_refused(result, f"T1.1: {BLANK_TASK_ID_MESSAGE}")
        self.assertEqual([f"T1.1: {BLANK_TASK_ID_MESSAGE}"], result.messages)

    def test_blank_placeholder_refuses_with_the_blank_message(self) -> None:
        """`taskgraph_emit._is_blank_task_id` semantics: a value containing
        `blank` (case-insensitively) is blank, never "not a UUID"."""
        plan = self._plan(_task_block("T1.1", "fx-t11-parity-test", "- **task_id:** (blank — backfilled at filing)"))

        result = node_gates.check_specifying(plan)

        self._assert_refused(result, f"T1.1: {BLANK_TASK_ID_MESSAGE}")
        self.assertNotIn(NOT_UUID_MESSAGE, " ".join(result.messages))

    def test_todo_value_refuses_as_not_a_uuid(self) -> None:
        plan = self._plan(_task_block("T1.1", "fx-t11-parity-test", "- **task_id:** todo"))

        result = node_gates.check_specifying(plan)

        self._assert_refused(result, f"T1.1: task_id todo {NOT_UUID_MESSAGE}")
        self.assertEqual([f"T1.1: task_id todo {NOT_UUID_MESSAGE}"], result.messages)

    def test_not_uuid_value_is_truncated_to_40_chars_in_the_message(self) -> None:
        plan = self._plan(_task_block("T1.1", "fx-t11-parity-test", _task_id_line("x" * 60)))

        result = node_gates.check_specifying(plan)

        self._assert_refused(result, f"T1.1: task_id {'x' * 40} {NOT_UUID_MESSAGE}")
        self.assertNotIn("x" * 41, " ".join(result.messages))

    def test_block_without_a_task_id_line_refuses_no_task_id_field(self) -> None:
        plan = self._plan(_task_block("T1.1", "fx-t11-parity-test", None))

        result = node_gates.check_specifying(plan)

        self._assert_refused(result, f"T1.1: {NO_TASK_ID_FIELD_MESSAGE}")
        self.assertEqual([f"T1.1: {NO_TASK_ID_FIELD_MESSAGE}"], result.messages)

    def test_module_blocks_contribute_nothing_and_are_not_refusals(self) -> None:
        """`## M1` (in the preamble) and a second, task-less `## M2` both carry
        `**external_id:**` and no `task_id`; only the two `####` blocks count."""
        second_module = "## M2 — Closeout\n\n**external_id:** `fx-m2-closeout`\n**Owner:** engineer\n\n"
        plan = self._plan(
            _task_block("T1.1", "fx-t11-parity-test", _task_id_line(UUID_1)),
            _task_block("T1.2", "fx-t12-suite-registration", _task_id_line(UUID_2)),
            second_module,
        )
        self.assertIn("## M1 — Contract parity", plan.read_text(encoding="utf-8"))

        result = node_gates.check_specifying(plan)

        self.assertTrue(result.ok, result.messages)
        self.assertEqual(["plan valid: 2 task blocks, all task_ids backfilled"], result.messages)

    def test_level_3_task_heading_is_not_a_task_block(self) -> None:
        """`plan_lint` S2 shape: a `### T1.1` heading is task-like at the
        wrong level and yields no block — a file with only that heading is
        the zero-blocks refusal, not a per-block one."""
        plan = self._write(
            PLAN_PREAMBLE + "\n### T1.1 — A task at the wrong level\n\n"
            + _task_id_line(UUID_1) + "\n- **external_id:** `fx-t11-parity-test`\n"
        )

        result = node_gates.check_specifying(plan)

        self._assert_refused(result, ZERO_BLOCKS_MESSAGE)
        self.assertEqual([ZERO_BLOCKS_MESSAGE], result.messages)

    def test_markdown_with_no_headings_refuses_zero_blocks(self) -> None:
        plan = self._write("Just prose, no headings at all.\n\n" + _task_id_line(UUID_1) + "\n")

        result = node_gates.check_specifying(plan)

        self._assert_refused(result, ZERO_BLOCKS_MESSAGE)

    def test_missing_file_refuses_naming_the_path(self) -> None:
        missing = self.tmp_path / "does-not-exist.md"

        result = node_gates.check_specifying(missing)

        self._assert_refused(result, f"plan file unreadable: {missing}")

    def test_undecodable_file_refuses_as_unreadable(self) -> None:
        self.plan_path.write_bytes(b"\xff\xfe\xfd not utf-8")

        result = node_gates.check_specifying(self.plan_path)

        self._assert_refused(result, f"plan file unreadable: {self.plan_path}")

    def test_three_blocks_one_blank_one_not_uuid_collects_both_in_document_order(self) -> None:
        """The driver fixes them in one pass: every per-block cause is
        collected, in document order, from a single call."""
        plan = self._plan(
            _task_block("T1.1", "fx-t11-parity-test", _task_id_line(UUID_1)),
            _task_block("T1.2", "fx-t12-suite-registration", "- **task_id:** "),
            _task_block("T1.3", "fx-t13-closeout", "- **task_id:** todo"),
        )

        result = node_gates.check_specifying(plan)

        self.assertFalse(result.ok)
        self.assertFalse(result.hold)
        self.assertEqual(
            [
                f"T1.2: {BLANK_TASK_ID_MESSAGE}",
                f"T1.3: task_id todo {NOT_UUID_MESSAGE}",
            ],
            result.messages,
        )

    def test_the_real_live_plan_passes_with_every_task_id_backfilled(self) -> None:
        """The live Plan, read-only. It carries 47 level-4 `#### T` blocks, every
        one backfilled. History: T4.5's brief expected 45 — the Plan header's
        stale `**Tasks:** 45` — while the body already held 46. Daniel
        authorised one addition on 2026-09-08 (T7.5, the engine explainer),
        making the honest count 47; the header was corrected then rather than
        left wrong in a new direction."""
        self.assertTrue(LIVE_PLAN.is_file(), LIVE_PLAN)

        result = node_gates.check_specifying(LIVE_PLAN)

        self.assertTrue(result.ok, result.messages)
        self.assertFalse(result.hold)
        self.assertEqual(["plan valid: 47 task blocks, all task_ids backfilled"], result.messages)


# ─────────────────────────────────────────────────────────────────────────────
# CLI level: `loop_state.py gate-pass --node specifying --plan PATH`
# ─────────────────────────────────────────────────────────────────────────────


class GatePassSpecifyingCLITests(unittest.TestCase):
    """Exit codes mirror `deciding` (D23/D33): 2 = `--node specifying` without
    `--plan`; 1 = refused (empty `--artifact` via the generic D6a guard, a
    missing/undecodable plan, any per-block `task_id` refusal); 0 = pass and
    freeze. No HOLD (3) path at N3. Scratch state reaches `specifying` by the
    legal path `init` → `set-node understanding` → `set-node deciding` →
    `set-node specifying` — `set_node` accepts any string, and `specifying`
    is a `LOOP_STATUS` value so `status` follows `current_node`."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name).resolve()
        self.workspace = self.tmp_path / "workspace"
        self.workspace.mkdir()
        self.input_path = self.tmp_path / "input.txt"
        self.input_path.write_text("Draft the thing.\n", encoding="utf-8")

        # A run-shaped layout: N3's three artifacts side by side, small and real.
        self.draft_dir = self.tmp_path / "03_draft"
        self.draft_dir.mkdir()
        self.prd_path = self.draft_dir / "PRD.md"
        self.prd_path.write_text("# PRD\n\n## Acceptance set\n\nA real, short spec.\n", encoding="utf-8")
        self.plan_path = self.draft_dir / "Plan.md"
        self._write_plan(
            _task_block("T1.1", "fx-t11-parity-test", _task_id_line(UUID_1)),
            _task_block("T1.2", "fx-t12-suite-registration", _task_id_line(UUID_2)),
        )
        self.workplan_path = self.draft_dir / "workplan.json"
        self.workplan_path.write_text(
            json.dumps({
                "project": "graph-machine-testbed",
                "work_items": [{"external_id": "fx-t11-parity-test"}, {"external_id": "fx-t12-suite-registration"}],
            }),
            encoding="utf-8",
        )

        init_result = _run_cli(
            "init", "--goal", "demo-goal",
            "--input", str(self.input_path),
            "--workspace", str(self.workspace),
        )
        self.assertEqual(0, init_result.returncode, init_result.stdout + init_result.stderr)
        self.state_path = self.workspace / "demo-goal" / "loop.state.json"
        for node in ("understanding", "deciding", "specifying"):
            set_node_result = _run_cli("set-node", str(self.state_path), "--node", node)
            self.assertEqual(0, set_node_result.returncode, set_node_result.stdout + set_node_result.stderr)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual("specifying", state["current_node"])

    def _write_plan(self, *blocks: str) -> None:
        self.plan_path.write_text(PLAN_PREAMBLE + "\n" + "".join(blocks), encoding="utf-8")

    def _gate_pass(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return _run_cli("gate-pass", str(self.state_path), "--node", "specifying", "--by", "test", *extra)

    def _artifacts(self) -> list[str]:
        return [str(self.prd_path), str(self.plan_path), str(self.workplan_path)]

    def _state_bytes(self) -> bytes:
        return self.state_path.read_bytes()

    def _assert_no_pass_marker(self, result: subprocess.CompletedProcess[str]) -> None:
        combined = result.stdout + result.stderr
        for marker in PASS_MARKERS:
            self.assertNotIn(marker, combined)

    def test_missing_plan_flag_is_usage_error_exit_2(self) -> None:
        """`--artifact` IS supplied so the exit is provably the `--plan`
        guard, not the D6a empty-artifact refusal."""
        before = self._state_bytes()

        result = self._gate_pass("--artifact", *self._artifacts())

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("gate-pass --node specifying requires --plan PATH (T4.5)", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_empty_artifact_list_refuses_exit_1(self) -> None:
        """D6a's generic guard now covers `specifying`: a VALID plan is
        supplied so the refusal is provably about the missing artifact."""
        before = self._state_bytes()

        result = self._gate_pass("--plan", str(self.plan_path))

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("empty --artifact list", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_missing_plan_file_refuses_exit_1_state_byte_identical(self) -> None:
        before = self._state_bytes()
        missing = self.draft_dir / "missing.md"

        result = self._gate_pass("--artifact", *self._artifacts(), "--plan", str(missing))

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn(f"plan file unreadable: {missing}", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_blank_task_id_refuses_exit_1_naming_the_block_label(self) -> None:
        self._write_plan(
            _task_block("T1.1", "fx-t11-parity-test", _task_id_line(UUID_1)),
            _task_block("T1.2", "fx-t12-suite-registration", "- **task_id:** "),
        )
        before = self._state_bytes()

        result = self._gate_pass("--artifact", *self._artifacts(), "--plan", str(self.plan_path))

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn(f"T1.2: {BLANK_TASK_ID_MESSAGE}", result.stderr)
        self._assert_no_pass_marker(result)
        self.assertEqual(before, self._state_bytes())

    def test_valid_plan_passes_exit_0_and_freezes_all_three_artifacts(self) -> None:
        result = self._gate_pass("--artifact", *self._artifacts(), "--plan", str(self.plan_path))

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        frozen_paths = [artifact["path"] for artifact in payload["artifacts"]]
        for path in self._artifacts():
            self.assertIn(path, frozen_paths)
        gate_summaries = [{"node": g["node"], "passed": g["passed"]} for g in payload["gates"]]
        self.assertIn({"node": "specifying", "passed": True}, gate_summaries)


# ─────────────────────────────────────────────────────────────────────────────
# Adapter proof: the shipped `draft-blank-task-id` fixture through
# GateBindingAdapter (mirrors DecideUnmappedComponentFixtureAdapterTests)
# ─────────────────────────────────────────────────────────────────────────────


class DraftBlankTaskIdFixtureAdapterTests(unittest.TestCase):
    def _context(self) -> AssertionContext:
        return AssertionContext(
            framework_root=HERE,
            repo_root=REPO_ROOT,
            verdicts_dir=HERE / "verdicts",
            traces_dir=HERE / "verdicts" / "traces",
        )

    def _evaluate(self):
        case_path = DRAFT_FIXTURE_DIR / "case.json"
        raw = json.loads(case_path.read_text(encoding="utf-8"))
        fixture = loader.Fixture(path=case_path, raw=raw)
        return GateBindingAdapter().evaluate(fixture, 0, self._context())

    def _gate_arguments(self) -> list[str]:
        """`gate.json`'s arguments with `{fixture_dir}` rendered exactly as
        the adapter renders it (`assertions/gate_binding.py`)."""
        descriptor = json.loads((DRAFT_FIXTURE_DIR / "gate.json").read_text(encoding="utf-8"))
        return [
            str(value).replace("{fixture_dir}", str(DRAFT_FIXTURE_DIR.resolve()))
            for value in descriptor["arguments"]
        ]

    def test_fixture_is_refused_by_the_gate_binding_adapter(self) -> None:
        evaluation = self._evaluate()

        self.assertEqual("pass", evaluation.observation.outcome, evaluation.observation.detail)
        self.assertTrue(evaluation.observation.evidence.payload["refused"])
        self.assertEqual("draft-gate-refusal", evaluation.observation.evidence.payload["error_class"])
        self.assertEqual("pass", evaluation.checks[0].status)

    def test_gate_arguments_run_directly_name_the_blank_block(self) -> None:
        """The adapter reports only exit + marker; the refusal TEXT is
        asserted by running `gate.json`'s exact arguments through the CLI —
        it must name `T1.2` and only `T1.2`."""
        state_path = DRAFT_FIXTURE_DIR / "loop.state.json"
        before = state_path.read_bytes()

        result = _run_cli(*self._gate_arguments())

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn(f"T1.2: {BLANK_TASK_ID_MESSAGE}", result.stderr)
        self.assertNotIn("T1.1:", result.stderr)
        self.assertNotIn("T1.3:", result.stderr)
        combined = result.stdout + result.stderr
        for marker in PASS_MARKERS:
            self.assertNotIn(marker, combined)
        self.assertEqual(before, state_path.read_bytes())

    def test_state_file_untouched_by_the_fixture_run(self) -> None:
        state_path = DRAFT_FIXTURE_DIR / "loop.state.json"
        before = state_path.read_bytes()

        self._evaluate()

        self.assertEqual(before, state_path.read_bytes())

    def test_precondition_holds_plan_lint_clean_only_second_block_blank(self) -> None:
        """The refusal must be the check's (`task_id is blank`), not the D6a
        empty-artifact guard's and not a plan-shape one — so `PRD.md` and
        `Plan.md` exist, `Plan.md` is `plan_lint` CLEAN, and of its three
        blocks only `T1.2`'s `task_id` is blank (`T1.3` carries the live
        Plan's annotated form)."""
        text = (DRAFT_FIXTURE_DIR / "Plan.md").read_text(encoding="utf-8")
        self.assertEqual([], plan_lint.lint_text(text))
        tasks, violations = plan_lint.parse_tasks(text.splitlines())
        self.assertEqual([], violations)
        self.assertEqual(["T1.1", "T1.2", "T1.3"], [task.label for task in tasks])
        values = {task.label: task.first("task_id")[0] for task in tasks}
        self.assertEqual("", values["T1.2"].strip())
        self.assertTrue(node_gates._is_backfilled_task_id(values["T1.1"]), values["T1.1"])
        self.assertTrue(node_gates._is_backfilled_task_id(values["T1.3"]), values["T1.3"])
        self.assertIn("*(backfilled 2026-09-07 from the live row)*", values["T1.3"])

        for name in ("PRD.md", "Plan.md", "original_input.md"):
            self.assertTrue((DRAFT_FIXTURE_DIR / name).is_file(), name)
        state = json.loads((DRAFT_FIXTURE_DIR / "loop.state.json").read_text(encoding="utf-8"))
        self.assertEqual("specifying", state["current_node"])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Unit level: check_executing() with a graph snapshot — closure identity
# (loop-ending follow-up, 2026-09-18). The gate stops inferring "was this
# legitimately closed" from local files and asks the source of truth who
# closed it: `work_items.completed_by`, stamped by the ops-server at each
# of the two doors that can set `state="done"`.
# ---------------------------------------------------------------------------
class CheckExecutingGraphSnapshotTests(unittest.TestCase):
    """The three legitimate closure paths the pre-snapshot gate could not
    tell apart: the verifier's committer identity, Daniel's Caelos console,
    and history that predates stamping."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.verifications_dir = self.tmp_path / "verifications"
        self.verifications_dir.mkdir()
        self.workplan_path = self.tmp_path / "workplan.json"
        self.reconciliation_path = self.tmp_path / "reconciliation.md"
        self.snapshot_path = self.tmp_path / "graph_snapshot.json"

    def _write_workplan(self, project: str, external_ids: list[str]) -> None:
        self.workplan_path.write_text(
            json.dumps({
                "project": project,
                "work_items": [{"external_id": eid} for eid in external_ids],
            }),
            encoding="utf-8",
        )

    def _write_reconciliation(self, dispositions: dict[str, str]) -> None:
        self.reconciliation_path.write_text(_reconciliation_text(dispositions), encoding="utf-8")

    def _write_snapshot(self, rows: list[dict[str, Any]]) -> None:
        self.snapshot_path.write_text(json.dumps(rows), encoding="utf-8")

    def _row(
        self,
        external_id: str,
        *,
        state: str = "done",
        completed_by: str | None = None,
        updated_at: str = "2026-09-17T12:00:00+00:00",
    ) -> dict[str, Any]:
        return {
            "external_id": external_id,
            "state": state,
            "completed_by": completed_by,
            "updated_at": updated_at,
        }

    def _write_verification(self, name: str, data: dict[str, Any]) -> None:
        (self.verifications_dir / name).write_text(json.dumps(data), encoding="utf-8")

    def _check(self) -> node_gates.GateResult:
        return node_gates.check_executing(
            self.workplan_path,
            self.verifications_dir,
            self.reconciliation_path,
            self.snapshot_path,
        )

    # -- the three legitimate paths ------------------------------------

    def test_committer_closed_row_passes_with_no_local_verifier_run(self) -> None:
        """The Class B/pre-verifier fix: the run file may be absent from THIS
        Mac (a different machine, a pruned directory) without making the
        closure illegitimate. The graph, not the filesystem, is the record."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self._write_snapshot([self._row("row-a", completed_by="graph-machine-committer")])

        result = self._check()

        self.assertTrue(result.ok, result.messages)
        self.assertFalse(result.hold)
        self.assertEqual([], result.messages)

    def test_console_closed_row_passes_outright(self) -> None:
        """Daniel's override. He closed it in Caelos deliberately."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self._write_snapshot([self._row("row-a", completed_by="caelos-console")])

        result = self._check()

        self.assertTrue(result.ok, result.messages)
        self.assertEqual([], result.messages)

    def test_grandfathered_row_before_the_verifier_epoch_passes(self) -> None:
        """Closed before the VERIFIER existed, so no run file can ever exist
        for it. Refusing it would be refusing history."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self._write_snapshot([
            self._row("row-a", completed_by=None, updated_at="2026-09-04T15:32:55+00:00"),
        ])

        result = self._check()

        self.assertTrue(result.ok, result.messages)
        self.assertEqual([], result.messages)

    # -- the refusals ---------------------------------------------------

    def test_unstamped_row_after_the_stamping_epoch_refuses(self) -> None:
        """Once stamping shipped every closure carries a label. An unstamped
        `done` row dated after it reached done by no door the server knows."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self._write_snapshot([
            self._row("row-a", completed_by=None, updated_at="2026-09-19T12:00:00+00:00"),
        ])

        result = self._check()

        self.assertFalse(result.ok)
        self.assertFalse(result.hold)
        self.assertEqual(1, len(result.messages))
        self.assertIn("no door the server knows", result.messages[0])

    def test_verifier_closed_row_between_the_two_epochs_passes(self) -> None:
        """THE BUG THIS FIX EXISTS FOR: the verifier closed 27 real rows
        between 2026-09-06 and 2026-09-18, before stamping could record it.
        A null label in that window must defer to the run file, not refuse."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self._write_snapshot([
            self._row("row-a", completed_by=None, updated_at="2026-09-08T12:00:00+00:00"),
        ])
        self._write_verification("a.json", _verification(
            external_id="row-a", project="proj", status="done",
            updated_at="2026-09-08T12:00:00+00:00",
            outcome="done", readback_state="done",
        ))

        result = self._check()

        self.assertTrue(result.ok, result.messages)

    def test_unverified_row_between_the_two_epochs_still_refuses(self) -> None:
        """The other half: a null label in that window is not a free pass.
        No run file, and after the verifier existed, is a real miss."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self._write_snapshot([
            self._row("row-a", completed_by=None, updated_at="2026-09-08T12:00:00+00:00"),
        ])

        result = self._check()

        self.assertFalse(result.ok)
        self.assertIn("no verifier run found", result.messages[0])

    def test_graph_disagrees_with_artifact_refuses(self) -> None:
        """The artifact claims done; the graph says otherwise. Fix the row,
        never the artifact."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self._write_snapshot([
            self._row("row-a", state="in-progress", completed_by=None),
        ])

        result = self._check()

        self.assertFalse(result.ok)
        self.assertIn("graph reads 'in-progress'", result.messages[0])
        self.assertIn("never the artifact", result.messages[0])

    def test_row_absent_from_snapshot_refuses(self) -> None:
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self._write_snapshot([self._row("other-row", completed_by="caelos-console")])

        result = self._check()

        self.assertFalse(result.ok)
        self.assertIn("absent from the graph snapshot", result.messages[0])

    def test_unknown_completed_by_label_refuses(self) -> None:
        """A third label means a third door appeared. The gate must not
        silently accept it — the one-door invariant is the design."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self._write_snapshot([self._row("row-a", completed_by="some-new-service")])

        result = self._check()

        self.assertFalse(result.ok)
        self.assertIn("some-new-service", result.messages[0])

    def test_unreadable_snapshot_refuses_without_crash(self) -> None:
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self.snapshot_path.write_text("{not a list}", encoding="utf-8")

        result = self._check()

        self.assertFalse(result.ok)
        self.assertIn("graph snapshot unreadable", result.messages[0])

    # -- Daniel's reversal survives -------------------------------------

    def test_committer_closed_row_with_undischarged_manual_still_holds(self) -> None:
        """Daniel's 2026-09-17 reversal is preserved: an undischarged manual
        criterion on committer-closed work still HOLDs the gate."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self._write_snapshot([self._row("row-a", completed_by="graph-machine-committer")])
        run = _verification(
            external_id="row-a", project="proj", status="unverifiable",
            updated_at="2026-09-17T00:00:00+00:00",
        )
        run["steps"] = {"landing": {"data": {"verdicts": [
            {"kind": "manual", "discharged": False, "failed": False,
             "statement": "Daniel confirms the thing reads as he described."},
        ]}}}
        self._write_verification("a.json", run)

        result = self._check()

        self.assertFalse(result.ok)
        self.assertTrue(result.hold)
        self.assertTrue(
            any("Daniel confirms the thing reads as he described." in m for m in result.messages),
            result.messages,
        )

    def test_console_closed_row_with_undischarged_manual_passes(self) -> None:
        """Daniel closing it in Caelos IS the discharge of a manual criterion.
        Holding the gate to ask him to confirm what he just confirmed by hand
        is the loop this whole design exists to end."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self._write_snapshot([self._row("row-a", completed_by="caelos-console")])
        run = _verification(
            external_id="row-a", project="proj", status="unverifiable",
            updated_at="2026-09-17T00:00:00+00:00",
        )
        run["steps"] = {"landing": {"data": {"verdicts": [
            {"kind": "manual", "discharged": False, "failed": False,
             "statement": "Daniel confirms the thing reads as he described."},
        ]}}}
        self._write_verification("a.json", run)

        result = self._check()

        self.assertTrue(result.ok, result.messages)
        self.assertFalse(result.hold)

    # -- non-done dispositions are untouched ----------------------------

    def test_live_test_and_descoped_rows_never_consult_the_snapshot(self) -> None:
        """`live-test`, `deferred` and `archived` are exempt by disposition;
        the snapshot must not resurrect a check for them."""
        self._write_workplan("proj", ["row-live", "row-def", "row-arch"])
        self._write_reconciliation({
            "row-live": "live-test", "row-def": "deferred", "row-arch": "archived",
        })
        self._write_snapshot([])  # deliberately empty

        result = self._check()

        self.assertTrue(result.ok, result.messages)
        self.assertEqual([], result.messages)

    # -- backward compatibility -----------------------------------------

    def test_omitting_the_snapshot_keeps_the_original_behaviour(self) -> None:
        """No snapshot => the pre-2026-09-18 path, byte for byte: a done row
        with no verifier run refuses."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})

        result = node_gates.check_executing(
            self.workplan_path, self.verifications_dir, self.reconciliation_path,
        )

        self.assertFalse(result.ok)
        self.assertIn("no verifier run found", result.messages[0])

    def test_workplan_uploader_label_refuses_by_name(self) -> None:
        """The batch plan-ingest door checks identity but refuses nothing on
        state, so a plan can declare a row finished and it lands unverified.
        Known door, not evidence — and it must refuse BY NAME, distinctly from
        an unrecognised label."""
        self._write_workplan("proj", ["row-a"])
        self._write_reconciliation({"row-a": "done"})
        self._write_snapshot([self._row("row-a", completed_by="workplan-uploader")])

        result = self._check()

        self.assertFalse(result.ok)
        self.assertIn("workplan-uploader", result.messages[0])
        self.assertIn("verifies nothing", result.messages[0])
        self.assertNotIn("unrecognised", result.messages[0])
