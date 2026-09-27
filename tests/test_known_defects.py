"""T5.2 — regression tests proving this port does not inherit three known
`graph_library` defects (source_references: `SprintTechReview_CTO_2026-09-26.md`
S1-S3):

  S1 — a state file `bin/loop_state.py init` writes carries no `_is_measured`
       key (any value) and no `_is_detected` key, anywhere in the file.
  S2 — re-filing a work item's criteria under its ORIGINAL idempotency key,
       with `update_acceptance_criteria=True`, mints a FRESH filing (a new
       filing id, a new idempotency key); the original filing's criteria are
       unchanged — filings are append-only.
  S3 — no history-rewrite gate ships anywhere under bin/, hyperspace/, skills/.

`probes/probe_known_defects.py` runs this file and writes the run's verdict.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from probes.scan_tree import scan  # noqa: E402


def _all_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _all_keys(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _all_keys(value)


def _candidate(external_id: str, idempotency_key: str, criteria: list[dict], **overrides) -> dict:
    payload = {
        "project": "kd-probe", "external_id": external_id, "name": "Known-defects probe item",
        "type": "task", "state": None, "parent_work_item": None, "assignee_agent": None,
        "team": None, "idempotency_key": idempotency_key,
        "specification": {
            "problem": "The regression test needs a real filed row to exercise the "
                       "store's append-only filing behavior end to end.",
            "why_it_matters": "Without a real filing, S2 cannot be PROVEN — only asserted.",
            "context_pointer": "tests/test_known_defects.py",
        },
        "source_references": [{"uri": "tests/test_known_defects.py"}],
        "effort_level": "quick", "module": None,
        "acceptance_criteria": criteria,
        "proposer_identity": "probe", "proposer_surface": "cli-mac",
        "uncertainty_notes": [],
    }
    payload.update(overrides)
    return payload


def _venv_python() -> Path:
    venv_python = ROOT / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


# ── S1 — no `_is_measured` / `_is_detected` in a fresh state file ──────────

def test_s1_no_measured_or_detected_keys_in_state_file(tmp_path):
    source = tmp_path / "original_input.md"
    source.write_text("known defects probe\n", encoding="utf-8")
    proc = subprocess.run(
        [str(_venv_python()), str(ROOT / "bin" / "loop_state.py"), "init",
         "--goal", "known-defects-probe", "--input", str(source), "--workspace", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    state_files = list(tmp_path.rglob("loop.state.json"))
    assert state_files, "loop_state.py init wrote no state file"

    keys: set[str] = set()
    for f in state_files:
        keys.update(_all_keys(json.loads(f.read_text(encoding="utf-8"))))

    assert "_is_measured" not in keys
    assert "_is_detected" not in keys


# ── S2 — a criteria update mints a fresh filing, the original is untouched ─

def test_s2_criteria_update_mints_a_fresh_filing(tmp_path):
    from hyperspace.store import Store
    from hyperspace.tools import call_tool

    db_path = tmp_path / ".hyperspace" / "graph.db"
    store = Store.init(db_path)
    try:
        call_tool(store, "upsert_project", {"code": "kd-probe", "name": "Known-defects probe"})

        v1 = [{"statement": "v1 exits 0 when run.", "verification": {"kind": "command_check", "check_id": "tests"}}]
        filed = call_tool(store, "upsert_work_item", _candidate("kd-probe:item-1", "item-1-create", v1))
        assert "error" not in filed, filed
        original_ref = filed["row"]["acceptance_criteria_ref"]
        original_filing_id = filed["filing_id"]

        v2 = [{"statement": "v2 exits 0 AND reads its own output.", "verification": {"kind": "command_check", "check_id": "tests"}}]
        refiled = call_tool(store, "upsert_work_item", _candidate(
            "kd-probe:item-1", "item-1-create", v2, update_acceptance_criteria=True,
        ))
        assert "error" not in refiled, refiled
        new_ref = refiled["row"]["acceptance_criteria_ref"]
        new_filing_id = refiled["filing_id"]

        assert new_filing_id != original_filing_id, "a criteria update must mint a NEW filing row"

        original_filing = store.get_filing(original_filing_id)
        new_filing = store.get_filing(new_filing_id)
        assert new_filing["idempotency_key"] != original_filing["idempotency_key"], (
            "the new filing must carry a FRESH idempotency key, never the original"
        )
        assert original_filing["idempotency_key"] == "item-1-create"

        assert store.resolve_criteria(new_ref)[0]["statement"] == v2[0]["statement"]
        assert store.resolve_criteria(original_ref)[0]["statement"] == v1[0]["statement"], (
            "the FIRST filing's criteria must be unchanged — filings are append-only"
        )
    finally:
        store.close()


# ── S3 — no history-rewrite gate ships ─────────────────────────────────────

def test_s3_no_history_rewrite_gate_ships():
    findings = scan(ROOT, ["bin", "hyperspace", "skills"],
                     ["filter-repo", "--history", "leak-scan"], case_insensitive=True)
    assert findings == [], [f"{f.path}:{f.line}: [{f.term}] {f.text}" for f in findings]
