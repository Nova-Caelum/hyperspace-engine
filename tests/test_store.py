"""T2.1 — the local SQLite store.

Covers: `Store.init` creates the file + all eleven tables (plus `meta`); one
insert-and-readback per table through `Store` methods, asserting every field
the console's types name is present; `add_filing` is append-only (two filings
for the same `external_id` under different idempotency keys leave the first
untouched); `acceptance_criteria_ref` round-trips through `resolve_criteria`;
a schema-version mismatch raises `SchemaVersionError` naming the migration
command; `hyperspace init` works as a subprocess and is idempotent.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from hyperspace.store import SCHEMA_VERSION, SchemaVersionError, Store

ROOT = Path(__file__).resolve().parents[1]

ELEVEN_TABLES = {
    "projects", "modules", "work_items", "work_item_relations", "cycles",
    "cycle_assignments", "initiatives", "initiative_links", "worklog",
    "verifier_runs", "filings",
}

# The closed, authoritative work_items column list (Plan T2.1 step 4's sample row).
WORK_ITEM_SAMPLE_ROW_FIELDS = {
    "id", "external_id", "project_code", "name", "type", "state", "module_id",
    "parent_work_item_id", "assignee_agent", "effort_level", "description",
    "source_references", "tags", "added_by", "idempotency_key", "created_at",
    "updated_at", "completed_at", "team", "acceptance_criteria",
    "acceptance_criteria_ref", "position", "completed_by", "uncertainty_notes",
}

# Fields the console's `WorkItem` FE type names (App.tsx L43-49) that also exist,
# verbatim, as backend columns (the rest — title/priority/assignee/blocked_by/
# doc_paths/cycle_id/parent_item_id/uuid/project_id — are FE-adapter renames of
# the backend fields above, not separate backend columns; see schema.sql header).
WORK_ITEM_TYPE_OVERLAP_FIELDS = {
    "id", "module_id", "description", "state", "team", "acceptance_criteria",
    "acceptance_criteria_ref", "position", "created_at", "source_references",
}


def _hyperspace_bin() -> Path:
    return Path(sys.executable).parent / "hyperspace"


# ── (a) init creates the file + eleven tables ───────────────────────────────


def test_init_creates_file_and_eleven_tables(tmp_path):
    db_path = tmp_path / ".hyperspace" / "graph.db"
    store = Store.init(db_path)
    try:
        assert db_path.exists()
        cur = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
        names = {row[0] for row in cur.fetchall()}
        assert ELEVEN_TABLES <= names
        assert "meta" in names
    finally:
        store.close()


# ── (b) one insert-and-readback per table ───────────────────────────────────


def test_project_round_trip(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        row = store.upsert_project(
            code="demo-project",
            name="Demo",
            description="A demo project.",
            status="in-progress",
            owner="maintainer",
            client="internal",
            folder_path="/workspace/demo-project",
            team=["engineer", "designer"],
        )
        for field in ["id", "name", "description", "folder_path", "created_at",
                      "status", "team", "owner", "client", "code"]:
            assert field in row, f"missing field: {field}"
        assert row["code"] == "demo-project"
        assert row["team"] == ["engineer", "designer"]

        readback = store.get_project("demo-project")
        assert readback == row
    finally:
        store.close()


def test_module_round_trip(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        row = store.upsert_module(
            project_code="demo-project",
            external_id="demo-project:mod-1",
            name="Module One",
            description="A module.",
            state="ready",
            folder_path="/workspace/demo-project/mod-1",
            team=["engineer"],
            acceptance_criteria="Every child item is done.",
        )
        for field in ["id", "external_id", "project_code", "name", "description",
                      "state", "parent_module_id", "folder_path", "team",
                      "acceptance_criteria", "acceptance_criteria_ref",
                      "created_at", "updated_at"]:
            assert field in row, f"missing field: {field}"
        assert row["team"] == ["engineer"]

        by_id = store.get_module(id=row["id"])
        by_external = store.get_module(external_id="demo-project:mod-1", project_code="demo-project")
        assert by_id == row == by_external
        assert store.list_modules("demo-project") == [row]
    finally:
        store.close()


def test_work_item_round_trip(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        row = store.upsert_work_item(
            project_code="demo-project",
            external_id="demo-project:wi-1",
            name="Do the thing",
            type="task",
            state="ready",
            assignee_agent="engineer",
            effort_level="medium",
            description="Do the thing.",
            source_references=[{"uri": "worklog entry abc"}],
            tags=["hyperspace-product"],
            added_by="engineer",
            idempotency_key="wi-1-create",
            team=["engineer"],
            acceptance_criteria="Exits 0.",
            position=1.0,
            uncertainty_notes=[],
        )

        missing = (WORK_ITEM_SAMPLE_ROW_FIELDS | WORK_ITEM_TYPE_OVERLAP_FIELDS) - row.keys()
        assert not missing, f"missing fields: {missing}"

        assert row["source_references"] == [{"uri": "worklog entry abc"}]
        assert row["tags"] == ["hyperspace-product"]
        assert row["team"] == ["engineer"]
        assert row["uncertainty_notes"] == []

        readback = store.get_work_item(id=row["id"])
        assert readback == row
        by_external = store.get_work_item(external_id="demo-project:wi-1", project_code="demo-project")
        assert by_external == row

        listed = store.list_work_items(project_code="demo-project")
        assert listed == [row]
    finally:
        store.close()


def test_cycle_round_trip(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        row = store.upsert_cycle(
            project_code="demo-project",
            external_id="demo-project:cycle-1",
            name="Cycle One",
            description="A cycle.",
            state="planned",
            start_date="2026-09-01",
            end_date="2026-09-30",
        )
        for field in ["id", "external_id", "project_code", "name", "description",
                      "state", "start_date", "end_date"]:
            assert field in row, f"missing field: {field}"
        assert store.list_cycles("demo-project") == [row]
    finally:
        store.close()


def test_initiative_round_trip(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        row = store.upsert_initiative(
            external_id="init-1",
            title="Initiative One",
            description="An initiative.",
            state="planned",
            doc_paths=["docs/init-1.md"],
        )
        for field in ["id", "external_id", "title", "description", "state", "doc_paths"]:
            assert field in row, f"missing field: {field}"
        assert row["doc_paths"] == ["docs/init-1.md"]
        assert store.get_initiative(external_id="init-1") == row
        assert store.get_initiative(id=row["id"]) == row
        assert store.list_initiatives() == [row]
    finally:
        store.close()


def test_worklog_round_trip(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        wi = store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            name="Do the thing", type="task", state="ready",
        )
        row = store.append_worklog(
            author="engineer",
            summary="Built the store.",
            project="demo-project",
            detailed="Full detail.",
            tags=["hsp-sqlite-store"],
            client=None,
            surface="desktop-mac",
            work_item_id=wi["id"],
        )
        for field in ["id", "author", "project", "summary", "detailed",
                      "created_at", "work_item_id"]:
            assert field in row, f"missing field: {field}"
        assert store.recent_worklog(limit=1) == [row]
        assert store.search_worklog(project="demo-project") == [row]
    finally:
        store.close()


def test_relations_and_cycle_assignments_and_initiative_links(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        wi1 = store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            name="A", type="task", state="ready",
        )
        wi2 = store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-2",
            name="B", type="task", state="ready",
        )
        relation = store.add_relation(
            project_code="demo-project", work_item_id=wi1["id"],
            related_work_item_id=wi2["id"], relation_type="blocks",
        )
        assert relation["relation_type"] == "blocks"
        assert store.list_relations(wi1["id"]) == [relation]
        store.remove_relation(wi1["id"], wi2["id"], "blocks")
        assert store.list_relations(wi1["id"]) == []

        cycle = store.upsert_cycle(project_code="demo-project", external_id="demo-project:cycle-1", name="C1")
        store.assign_cycle(cycle["id"], wi1["id"])
        store.unassign_cycle(cycle["id"], wi1["id"])

        init = store.upsert_initiative(external_id="init-1", title="Init")
        store.link_initiative(init["id"], "work_item", wi1["external_id"])
        links = store.list_initiative_links(init["id"])
        assert links and links[0]["link_type"] == "work_item"
        store.unlink_initiative(init["id"], "work_item", wi1["external_id"])
        assert store.list_initiative_links(init["id"]) == []
    finally:
        store.close()


def test_verifier_run_round_trip(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        row = store.record_verifier_run(
            external_id="demo-project:wi-1",
            project_code="demo-project",
            outcome="done",
            judge="evidence-judge",
            steps=[{"name": "vet", "verdict": "pass"}],
        )
        for field in ["id", "external_id", "project_code", "started_at",
                      "finished_at", "outcome", "judge", "steps", "error"]:
            assert field in row, f"missing field: {field}"
        assert row["steps"] == [{"name": "vet", "verdict": "pass"}]
        assert store.get_verifier_run(row["id"]) == row
    finally:
        store.close()


# ── (c) filings are append-only ─────────────────────────────────────────────


def test_filings_are_append_only(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            name="Do the thing", type="task", state="ready",
        )

        candidate_v1 = {"name": "Do the thing", "acceptance_criteria": [{"statement": "v1"}]}
        filing_id_1 = store.add_filing(
            external_id="demo-project:wi-1", project_code="demo-project",
            idempotency_key="key-1", candidate=candidate_v1,
        )
        filing_1 = store.get_filing(filing_id_1)
        candidate_v1_bytes = filing_1["candidate_json"]

        candidate_v2 = {"name": "Do the thing", "acceptance_criteria": [{"statement": "v2"}]}
        filing_id_2 = store.add_filing(
            external_id="demo-project:wi-1", project_code="demo-project",
            idempotency_key="key-2", candidate=candidate_v2,
        )

        assert filing_id_1 != filing_id_2

        filing_1_again = store.get_filing(filing_id_1)
        assert filing_1_again["candidate_json"] == candidate_v1_bytes
        assert json.loads(filing_1_again["candidate_json"]) == candidate_v1

        filing_2 = store.get_filing(filing_id_2)
        assert json.loads(filing_2["candidate_json"]) == candidate_v2
        assert filing_2["id"] == filing_id_2
    finally:
        store.close()


# ── (d) acceptance_criteria_ref round-trips through resolve_criteria ────────


def test_acceptance_criteria_ref_resolves(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            name="Do the thing", type="task", state="ready",
        )
        criteria = [{"statement": "Exits 0.", "verification": {"kind": "manual"}}]
        filing_id = store.add_filing(
            external_id="demo-project:wi-1", project_code="demo-project",
            idempotency_key="key-1",
            candidate={"name": "Do the thing", "acceptance_criteria": criteria},
        )
        expected_ref = f"graph://filing/{filing_id}/item/demo-project:wi-1#acceptance_criteria"

        wi = store.get_work_item(external_id="demo-project:wi-1", project_code="demo-project")
        assert wi["acceptance_criteria_ref"] == expected_ref

        resolved = store.resolve_criteria(expected_ref)
        assert resolved == criteria
    finally:
        store.close()


# ── (e) schema-version mismatch raises SchemaVersionError ───────────────────


def test_schema_version_mismatch_raises(tmp_path):
    db_path = tmp_path / ".hyperspace" / "graph.db"
    store = Store.init(db_path)
    store.close()

    raw = sqlite3.connect(str(db_path))
    raw.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION + 1),))
    raw.commit()
    raw.close()

    with pytest.raises(SchemaVersionError) as exc_info:
        Store.open(db_path)
    assert "hyperspace migrate" in str(exc_info.value)


# ── (f) `hyperspace init` as a subprocess, idempotent ────────────────────────


def test_hyperspace_init_subprocess_creates_db_and_is_idempotent(tmp_path):
    hyperspace_bin = _hyperspace_bin()
    assert hyperspace_bin.exists(), f"expected console script at {hyperspace_bin}"

    project_dir = tmp_path / "empty-project"
    project_dir.mkdir()

    first = subprocess.run(
        [str(hyperspace_bin), "init", "--dir", str(project_dir)],
        capture_output=True, text=True,
    )
    assert first.returncode == 0, first.stderr
    db_path = project_dir / ".hyperspace" / "graph.db"
    assert db_path.exists()
    assert str(db_path) in first.stdout

    second = subprocess.run(
        [str(hyperspace_bin), "init", "--dir", str(project_dir)],
        capture_output=True, text=True,
    )
    assert second.returncode == 0, second.stderr
    assert "already initialised" in second.stdout


# ── (g) closure auto-log — v0.1.1 item 1 ─────────────────────────────────────
#
# One store helper, called from both doors that can flip a work item INTO
# `done`: the verifier's `set_work_item_state` and the console's
# `upsert_work_item`. Inserts one `worklog` row (`tags: ["closure"]`);
# idempotent per transition (an already-done row logs nothing more); a
# logging failure is swallowed and never blocks or reverts the flip.


def test_verifier_door_closure_logs_one_worklog_row(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        wi = store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            name="Do the thing", type="task", state="ready",
        )
        row = store.set_work_item_state(wi["id"], "done", completed_by="hyperspace-verifier")
        assert row["state"] == "done"

        entries = store.search_worklog(tags=["closure"])
        assert len(entries) == 1
        entry = entries[0]
        assert entry["author"] == "hyperspace-verifier"
        assert entry["project"] == "demo-project"
        assert entry["work_item_id"] == wi["id"]
        assert entry["summary"] == "demo-project:wi-1 closed done (hyperspace-verifier)"
        assert entry["tags"] == ["closure"]
    finally:
        store.close()


def test_console_door_closure_logs_one_worklog_row(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            name="Do the thing", type="task", state="ready",
        )
        row = store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            state="done", completed_by="hyperspace-console",
        )
        assert row["state"] == "done"

        entries = store.search_worklog(tags=["closure"])
        assert len(entries) == 1
        entry = entries[0]
        assert entry["author"] == "hyperspace-console"
        assert entry["project"] == "demo-project"
        assert entry["work_item_id"] == row["id"]
        assert entry["summary"] == "demo-project:wi-1 closed done (hyperspace-console)"
    finally:
        store.close()


def test_console_door_create_straight_to_done_logs_one_row(tmp_path):
    """The console can also file a NEW row already `state="done"` — no prior
    `ready` row exists, so `existing is None` at write time; still one row,
    not zero (a `None`-guard bug would silently skip a brand-new closure)."""
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        row = store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-new",
            name="Do the thing", type="task", state="done",
            completed_by="hyperspace-console",
        )
        assert row["state"] == "done"
        entries = store.search_worklog(tags=["closure"])
        assert len(entries) == 1
        assert entries[0]["work_item_id"] == row["id"]
    finally:
        store.close()


def test_closure_log_idempotent_on_already_done_verifier_door(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        wi = store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            name="Do the thing", type="task", state="ready",
        )
        store.set_work_item_state(wi["id"], "done", completed_by="hyperspace-verifier")
        # re-writing (or re-reading) an already-done row logs nothing more.
        store.set_work_item_state(wi["id"], "done", completed_by="hyperspace-verifier")
        assert len(store.search_worklog(tags=["closure"])) == 1
    finally:
        store.close()


def test_closure_log_idempotent_on_already_done_console_door(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            name="Do the thing", type="task", state="ready",
        )
        store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            state="done", completed_by="hyperspace-console",
        )
        # a second console write against the same already-done row (e.g. an
        # unrelated field edit that resends state="done") logs nothing more.
        store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            state="done", completed_by="hyperspace-console",
        )
        assert len(store.search_worklog(tags=["closure"])) == 1
    finally:
        store.close()


def test_closure_log_failure_does_not_block_the_flip(tmp_path):
    """A broken worklog insert (table dropped, simulating any logging
    failure) must never block or revert the state flip it was triggered by."""
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        wi = store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            name="Do the thing", type="task", state="ready",
        )
        store._conn.execute("DROP TABLE worklog")
        store._conn.commit()

        row = store.set_work_item_state(wi["id"], "done", completed_by="hyperspace-verifier")
        assert row["state"] == "done"
        assert row["completed_by"] == "hyperspace-verifier"

        # the connection must still be usable afterward — no transaction left
        # dangling by the swallowed failure.
        readback = store.get_work_item(id=wi["id"])
        assert readback["state"] == "done"
    finally:
        store.close()


def test_list_verifier_runs_filters_by_external_id_and_project(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        store.record_verifier_run(external_id="demo-project:a", project_code="demo-project", outcome="done")
        store.record_verifier_run(external_id="demo-project:b", project_code="demo-project", outcome="refused")

        by_ext = store.list_verifier_runs("demo-project:a")
        assert len(by_ext) == 1
        assert by_ext[0]["external_id"] == "demo-project:a"
        assert by_ext[0]["outcome"] == "done"

        by_ext_and_project = store.list_verifier_runs("demo-project:a", project_code="demo-project")
        assert len(by_ext_and_project) == 1

        by_ext_wrong_project = store.list_verifier_runs("demo-project:a", project_code="other-project")
        assert by_ext_wrong_project == []
    finally:
        store.close()


def test_no_closure_log_on_non_done_transition(tmp_path):
    store = Store.init(tmp_path / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        wi = store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            name="Do the thing", type="task", state="ready",
        )
        store.set_work_item_state(wi["id"], "in-progress", completed_by=None)
        assert store.search_worklog(tags=["closure"]) == []
    finally:
        store.close()
