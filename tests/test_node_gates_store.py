"""tests/test_node_gates_store.py — v0.1.1 item 3: the Build gate's
manual-criterion HOLD (exit 3) against the LOCAL verifier's store-recorded
runs, not just run FILES under `misc/verifications/`.

Today `check_executing` only looks for verifier run files; the local
verifier records its runs in the store's `verifier_runs` table instead
(`hyperspace/verify/compose.py::StoreStateWriter`), so the HOLD never fired
against a local project. Covers: `check_executing(store_path=...)` reads a
store-recorded run through the SAME judgement it applies to run files
(`_row_passes` / `_undischarged_manual_lines`) — an undischarged `manual`
criterion HOLDs (exit 3) naming the row, a `done` run passes, and the file
+ `--graph-snapshot` paths are unaffected when no store resolves. Also
covers `resolve_project_dir` (shared with item 2's gate-exit log).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import node_gates  # noqa: E402

from hyperspace.store import Store  # noqa: E402

PROJECT = "demo-project"


def _workplan(tmp_path: Path, external_id: str) -> Path:
    path = tmp_path / "workplan.json"
    path.write_text(json.dumps({"project": PROJECT, "work_items": [{"external_id": external_id}]}), encoding="utf-8")
    return path


def _reconciliation(tmp_path: Path, external_id: str) -> Path:
    path = tmp_path / "RECONCILIATION.md"
    path.write_text(f"- {external_id} → done\n", encoding="utf-8")
    return path


def _verification_state(
    *, external_id: str, outcome: str, updated_at: str, manual_discharged: bool | None = None,
) -> dict:
    """A minimal `VerificationState`-shaped dict — the same shape
    `verifier_runs.steps` holds (`compose.py::StoreStateWriter.write`:
    `steps=state.model_dump(mode="json")`), field-for-field what a run FILE
    holds too."""
    state: dict = {
        "status": outcome,
        "project": PROJECT,
        "external_id": external_id,
        "updated_at": updated_at,
        "final_result": {"outcome": outcome, "readback_state": "done" if outcome == "done" else None},
    }
    if manual_discharged is not None:
        state["steps"] = {
            "landing": {
                "status": "passed" if manual_discharged else "uncertain",
                "data": {"verdicts": [
                    {"kind": "manual", "statement": "The user confirms the result.",
                     "discharged": manual_discharged, "failed": False},
                ]},
            }
        }
    return state


# ── check_executing reads store-recorded runs ────────────────────────────────


def test_check_executing_holds_on_undischarged_manual_in_store(tmp_path):
    project_dir = tmp_path / "project"
    store = Store.init(project_dir / ".hyperspace" / "graph.db")
    store.upsert_project(code=PROJECT, name="Demo")
    ext = f"{PROJECT}:m"
    store.record_verifier_run(
        external_id=ext, project_code=PROJECT, outcome="unverifiable",
        steps=_verification_state(
            external_id=ext, outcome="unverifiable",
            updated_at="2026-09-27T00:00:00+00:00", manual_discharged=False,
        ),
    )
    store.close()

    result = node_gates.check_executing(
        workplan=_workplan(tmp_path, ext),
        verifications_dir=tmp_path / "no-files-here",
        reconciliation=_reconciliation(tmp_path, ext),
        store_path=project_dir / ".hyperspace" / "graph.db",
    )
    assert result.hold is True
    assert result.ok is False
    assert any(ext in m for m in result.messages), result.messages


def test_check_executing_passes_on_done_run_in_store(tmp_path):
    project_dir = tmp_path / "project"
    store = Store.init(project_dir / ".hyperspace" / "graph.db")
    store.upsert_project(code=PROJECT, name="Demo")
    ext = f"{PROJECT}:m2"
    store.record_verifier_run(
        external_id=ext, project_code=PROJECT, outcome="done",
        steps=_verification_state(external_id=ext, outcome="done", updated_at="2026-09-27T00:00:00+00:00"),
    )
    store.close()

    result = node_gates.check_executing(
        workplan=_workplan(tmp_path, ext),
        verifications_dir=tmp_path / "no-files-here",
        reconciliation=_reconciliation(tmp_path, ext),
        store_path=project_dir / ".hyperspace" / "graph.db",
    )
    assert result.ok is True
    assert result.hold is False


def test_check_executing_newest_run_wins_between_file_and_store(tmp_path):
    """The store and a run file compete on equal footing — newest
    `updated_at` decides, same rule `_latest_verification` already applies
    between multiple files."""
    project_dir = tmp_path / "project"
    store = Store.init(project_dir / ".hyperspace" / "graph.db")
    store.upsert_project(code=PROJECT, name="Demo")
    ext = f"{PROJECT}:m4"
    store.record_verifier_run(
        external_id=ext, project_code=PROJECT, outcome="refused",
        steps=_verification_state(external_id=ext, outcome="refused", updated_at="2026-09-27T00:00:00+00:00"),
    )
    store.close()

    verifications_dir = tmp_path / "misc" / "verifications"
    verifications_dir.mkdir(parents=True)
    newer_file = {
        **_verification_state(external_id=ext, outcome="done", updated_at="2026-09-27T01:00:00+00:00"),
    }
    (verifications_dir / "run-1.json").write_text(json.dumps(newer_file), encoding="utf-8")

    result = node_gates.check_executing(
        workplan=_workplan(tmp_path, ext),
        verifications_dir=verifications_dir,
        reconciliation=_reconciliation(tmp_path, ext),
        store_path=project_dir / ".hyperspace" / "graph.db",
    )
    assert result.ok is True, result.messages


def test_check_executing_without_store_path_refuses_as_before(tmp_path):
    """No `store_path` at all: unchanged behaviour — refuses missing, never
    a store-shaped surprise. The documented refusal string is unchanged."""
    ext = f"{PROJECT}:m3"
    result = node_gates.check_executing(
        workplan=_workplan(tmp_path, ext),
        verifications_dir=tmp_path / "no-files-here",
        reconciliation=_reconciliation(tmp_path, ext),
    )
    assert result.ok is False
    assert result.hold is False
    assert any("no verifier run found" in m for m in result.messages), result.messages


def test_check_executing_store_path_that_does_not_exist_is_silently_ignored(tmp_path):
    """A `store_path` naming a file that isn't a valid store must not crash
    the gate — it just falls back to file-only behaviour."""
    ext = f"{PROJECT}:m5"
    result = node_gates.check_executing(
        workplan=_workplan(tmp_path, ext),
        verifications_dir=tmp_path / "no-files-here",
        reconciliation=_reconciliation(tmp_path, ext),
        store_path=tmp_path / "does-not-exist" / "graph.db",
    )
    assert result.ok is False
    assert result.hold is False
    assert any("no verifier run found" in m for m in result.messages), result.messages


# ── resolve_project_dir (shared with item 2) ─────────────────────────────────


def test_resolve_project_dir_explicit_wins_when_store_exists(tmp_path):
    project_dir = tmp_path / "explicit-project"
    Store.init(project_dir / ".hyperspace" / "graph.db").close()
    run_dir = tmp_path / "unrelated" / "run"
    run_dir.mkdir(parents=True)

    resolved = node_gates.resolve_project_dir(run_dir, explicit=project_dir)
    assert resolved == project_dir


def test_resolve_project_dir_explicit_wrong_path_is_none(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    resolved = node_gates.resolve_project_dir(run_dir, explicit=tmp_path / "nonexistent")
    assert resolved is None


def test_resolve_project_dir_walks_up_from_run_folder(tmp_path):
    project_dir = tmp_path / "project"
    Store.init(project_dir / ".hyperspace" / "graph.db").close()
    run_dir = project_dir / "hyperspace" / "runs" / "some-slug"
    run_dir.mkdir(parents=True)

    resolved = node_gates.resolve_project_dir(run_dir)
    assert resolved == project_dir


def test_resolve_project_dir_returns_none_when_nothing_resolves(tmp_path):
    run_dir = tmp_path / "no-project" / "run"
    run_dir.mkdir(parents=True)
    assert node_gates.resolve_project_dir(run_dir) is None
