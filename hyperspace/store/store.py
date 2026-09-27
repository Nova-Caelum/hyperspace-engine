"""hyperspace/store/store.py — the product's local SQLite store (row T2.1).

One SQLite file, one `Store` class that owns it. Every table the console reads,
with the console's column names (see `schema.sql`'s header for the field-name
provenance), plus an append-only `filings` table that keeps each work item exactly
as it was filed. No raw SQL leaves this module — every consumer goes through
`Store`.

Contract validation (placeholder refusal, S2 fresh-key idempotency logic) is the
`hyperspace/tools/**` row's job, not this one. This module validates only the
closed enum sets below, and only inside `Store` (not as SQL CHECK constraints),
so a future value-set migration is a one-file change.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA_VERSION = 1

_SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "schema.sql"

# Set A — task_workflow_state (work_items, modules). App.tsx L20-21.
WORK_ITEM_STATES = frozenset(
    {"pending-review", "ready", "in-progress", "blocked", "done", "deferred", "archived"}
)
# Set B — project_lifecycle_state (projects, cycles, initiatives). App.tsx L22-23.
LIFECYCLE_STATES = frozenset(
    {"planned", "in-progress", "paused", "completed", "closed", "archived"}
)
RELATION_TYPES = frozenset(
    {"blocks", "blocked-by", "follow-up-of", "duplicate-of", "relates-to"}
)
LINK_TYPES = frozenset({"project", "module", "work_item"})

_JSON_LIST_FIELDS = {
    "team": [],
    "doc_paths": [],
    "tags": [],
    "source_references": None,
    "uncertainty_notes": [],
    "steps": None,
}


class SchemaVersionError(RuntimeError):
    """Raised by `Store.open`/`Store.init` when an existing db's schema_version
    does not match the code's `SCHEMA_VERSION`."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def _load(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)


def _row_to_dict(row: sqlite3.Row | None, json_fields: Iterable[str] = ()) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for field in json_fields:
        if field in d:
            d[field] = _load(d[field], _JSON_LIST_FIELDS.get(field))
    return d


def _validate_enum(value: str | None, allowed: frozenset, field: str) -> None:
    if value is not None and value not in allowed:
        raise ValueError(f"{field}={value!r} is not one of {sorted(allowed)}")


class Store:
    """Owns one SQLite file. No raw SQL leaves this module."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        # PRAGMA foreign_keys is per-connection in SQLite (it does not persist in the
        # file the way journal_mode does) — set it here, on every Store, not only in
        # `init`'s one-time schema creation.
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")

    # ── lifecycle ────────────────────────────────────────────────────────────

    @classmethod
    def init(cls, path: str | Path) -> "Store":
        """Create the db + schema if absent; idempotent — a second call against
        an existing, correctly-versioned file is a no-op open."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not path.exists()
        store = cls(path)
        if is_new:
            store._conn.executescript(_SCHEMA_SQL_PATH.read_text(encoding="utf-8"))
            store._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            store._conn.commit()
        else:
            store._check_schema_version()
        return store

    @classmethod
    def open(cls, path: str | Path) -> "Store":
        """Open an existing db. Refuses on schema_version mismatch."""
        store = cls(path)
        store._check_schema_version()
        return store

    def _check_schema_version(self) -> None:
        cur = self._conn.execute("SELECT value FROM meta WHERE key = 'schema_version'")
        row = cur.fetchone()
        version = int(row["value"]) if row is not None else None
        if version != SCHEMA_VERSION:
            self._conn.close()
            raise SchemaVersionError(
                f"schema_version mismatch: db has {version!r}, code expects "
                f"{SCHEMA_VERSION} — run: hyperspace migrate"
            )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc_info) -> bool:
        self.close()
        return False

    # ── projects ─────────────────────────────────────────────────────────────

    def upsert_project(self, code: str, **fields: Any) -> dict:
        _validate_enum(fields.get("status"), LIFECYCLE_STATES, "status")
        now = _now()
        existing = self.get_project(code)
        row = {
            "code": code,
            "id": fields.get("id") or (existing or {}).get("id") or _new_id(),
            "name": fields.get("name", (existing or {}).get("name")),
            "description": fields.get("description", (existing or {}).get("description")),
            "status": fields.get("status", (existing or {}).get("status")),
            "parent_code": fields.get("parent_code", (existing or {}).get("parent_code")),
            "owner": fields.get("owner", (existing or {}).get("owner")),
            "client": fields.get("client", (existing or {}).get("client")),
            "next_action": fields.get("next_action", (existing or {}).get("next_action")),
            "folder_path": fields.get("folder_path", (existing or {}).get("folder_path")),
            "team": _dump(fields.get("team", (existing or {}).get("team") or [])),
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        self._conn.execute(
            """
            INSERT INTO projects (code, id, name, description, status, parent_code,
                owner, client, next_action, folder_path, team, created_at, updated_at)
            VALUES (:code, :id, :name, :description, :status, :parent_code, :owner,
                :client, :next_action, :folder_path, :team, :created_at, :updated_at)
            ON CONFLICT(code) DO UPDATE SET
                id=excluded.id, name=excluded.name, description=excluded.description,
                status=excluded.status, parent_code=excluded.parent_code,
                owner=excluded.owner, client=excluded.client,
                next_action=excluded.next_action, folder_path=excluded.folder_path,
                team=excluded.team, updated_at=excluded.updated_at
            """,
            row,
        )
        self._conn.commit()
        return self.get_project(code)

    def get_project(self, code: str) -> dict | None:
        cur = self._conn.execute("SELECT * FROM projects WHERE code = ?", (code,))
        return _row_to_dict(cur.fetchone(), ["team"])

    def list_projects(self) -> list[dict]:
        cur = self._conn.execute("SELECT * FROM projects ORDER BY code")
        return [_row_to_dict(r, ["team"]) for r in cur.fetchall()]

    # ── modules ──────────────────────────────────────────────────────────────

    def upsert_module(self, project_code: str, external_id: str, **fields: Any) -> dict:
        _validate_enum(fields.get("state"), WORK_ITEM_STATES, "state")
        existing = self.get_module(project_code=project_code, external_id=external_id)
        now = _now()
        row = {
            "id": (existing or {}).get("id") or fields.get("id") or _new_id(),
            "external_id": external_id,
            "project_code": project_code,
            "name": fields.get("name", (existing or {}).get("name")),
            "description": fields.get("description", (existing or {}).get("description")),
            "state": fields.get("state", (existing or {}).get("state")),
            "parent_module_id": fields.get("parent_module_id", (existing or {}).get("parent_module_id")),
            "folder_path": fields.get("folder_path", (existing or {}).get("folder_path")),
            "team": _dump(fields.get("team", (existing or {}).get("team") or [])),
            "acceptance_criteria": fields.get("acceptance_criteria", (existing or {}).get("acceptance_criteria")),
            "acceptance_criteria_ref": fields.get("acceptance_criteria_ref", (existing or {}).get("acceptance_criteria_ref")),
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        self._conn.execute(
            """
            INSERT INTO modules (id, external_id, project_code, name, description,
                state, parent_module_id, folder_path, team, acceptance_criteria,
                acceptance_criteria_ref, created_at, updated_at)
            VALUES (:id, :external_id, :project_code, :name, :description, :state,
                :parent_module_id, :folder_path, :team, :acceptance_criteria,
                :acceptance_criteria_ref, :created_at, :updated_at)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, description=excluded.description,
                state=excluded.state, parent_module_id=excluded.parent_module_id,
                folder_path=excluded.folder_path, team=excluded.team,
                acceptance_criteria=excluded.acceptance_criteria,
                acceptance_criteria_ref=excluded.acceptance_criteria_ref,
                updated_at=excluded.updated_at
            """,
            row,
        )
        self._conn.commit()
        return self.get_module(id=row["id"])

    def get_module(self, id: str | None = None, external_id: str | None = None, project_code: str | None = None) -> dict | None:
        if id is not None:
            cur = self._conn.execute("SELECT * FROM modules WHERE id = ?", (id,))
        elif external_id is not None and project_code is not None:
            cur = self._conn.execute(
                "SELECT * FROM modules WHERE project_code = ? AND external_id = ?",
                (project_code, external_id),
            )
        elif external_id is not None:
            cur = self._conn.execute("SELECT * FROM modules WHERE external_id = ?", (external_id,))
        else:
            raise ValueError("get_module requires id, or external_id (optionally with project_code)")
        return _row_to_dict(cur.fetchone(), ["team"])

    def list_modules(self, project_code: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM modules WHERE project_code = ? ORDER BY external_id", (project_code,)
        )
        return [_row_to_dict(r, ["team"]) for r in cur.fetchall()]

    # ── work_items ───────────────────────────────────────────────────────────

    _WORK_ITEM_JSON_FIELDS = ["source_references", "tags", "team", "uncertainty_notes"]

    def upsert_work_item(self, project_code: str, external_id: str, **fields: Any) -> dict:
        """Row write only — contract validation (placeholder refusal, required
        fields on create, etc.) is the `hyperspace/tools/**` row's job."""
        _validate_enum(fields.get("state"), WORK_ITEM_STATES, "state")
        existing = self.get_work_item(external_id=external_id, project_code=project_code)
        now = _now()
        row = {
            "id": (existing or {}).get("id") or fields.get("id") or _new_id(),
            "external_id": external_id,
            "project_code": project_code,
            "name": fields.get("name", (existing or {}).get("name")),
            "type": fields.get("type", (existing or {}).get("type")),
            "state": fields.get("state", (existing or {}).get("state")),
            "module_id": fields.get("module_id", (existing or {}).get("module_id")),
            "parent_work_item_id": fields.get("parent_work_item_id", (existing or {}).get("parent_work_item_id")),
            "assignee_agent": fields.get("assignee_agent", (existing or {}).get("assignee_agent")),
            "effort_level": fields.get("effort_level", (existing or {}).get("effort_level")),
            "description": fields.get("description", (existing or {}).get("description")),
            "source_references": _dump(fields.get("source_references", (existing or {}).get("source_references"))),
            "tags": _dump(fields.get("tags", (existing or {}).get("tags") or [])),
            "added_by": fields.get("added_by", (existing or {}).get("added_by")),
            "idempotency_key": fields.get("idempotency_key", (existing or {}).get("idempotency_key")),
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
            "completed_at": fields.get("completed_at", (existing or {}).get("completed_at")),
            "team": _dump(fields.get("team", (existing or {}).get("team") or [])),
            "acceptance_criteria": fields.get("acceptance_criteria", (existing or {}).get("acceptance_criteria")),
            "acceptance_criteria_ref": fields.get("acceptance_criteria_ref", (existing or {}).get("acceptance_criteria_ref")),
            "position": fields.get("position", (existing or {}).get("position")),
            "completed_by": fields.get("completed_by", (existing or {}).get("completed_by")),
            "uncertainty_notes": _dump(fields.get("uncertainty_notes", (existing or {}).get("uncertainty_notes") or [])),
        }
        self._conn.execute(
            """
            INSERT INTO work_items (id, external_id, project_code, name, type, state,
                module_id, parent_work_item_id, assignee_agent, effort_level,
                description, source_references, tags, added_by, idempotency_key,
                created_at, updated_at, completed_at, team, acceptance_criteria,
                acceptance_criteria_ref, position, completed_by, uncertainty_notes)
            VALUES (:id, :external_id, :project_code, :name, :type, :state,
                :module_id, :parent_work_item_id, :assignee_agent, :effort_level,
                :description, :source_references, :tags, :added_by, :idempotency_key,
                :created_at, :updated_at, :completed_at, :team, :acceptance_criteria,
                :acceptance_criteria_ref, :position, :completed_by, :uncertainty_notes)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, type=excluded.type, state=excluded.state,
                module_id=excluded.module_id,
                parent_work_item_id=excluded.parent_work_item_id,
                assignee_agent=excluded.assignee_agent,
                effort_level=excluded.effort_level, description=excluded.description,
                source_references=excluded.source_references, tags=excluded.tags,
                added_by=excluded.added_by, idempotency_key=excluded.idempotency_key,
                updated_at=excluded.updated_at, completed_at=excluded.completed_at,
                team=excluded.team, acceptance_criteria=excluded.acceptance_criteria,
                acceptance_criteria_ref=excluded.acceptance_criteria_ref,
                position=excluded.position, completed_by=excluded.completed_by,
                uncertainty_notes=excluded.uncertainty_notes
            """,
            row,
        )
        self._conn.commit()
        return self.get_work_item(id=row["id"])

    def get_work_item(self, id: str | None = None, external_id: str | None = None, project_code: str | None = None) -> dict | None:
        if id is not None:
            cur = self._conn.execute("SELECT * FROM work_items WHERE id = ?", (id,))
        elif external_id is not None and project_code is not None:
            cur = self._conn.execute(
                "SELECT * FROM work_items WHERE project_code = ? AND external_id = ?",
                (project_code, external_id),
            )
        elif external_id is not None:
            # external_id is unique per project, not globally — a bare lookup with
            # no project_code is ambiguous across projects, and returns whichever
            # row sqlite happens to order first. Callers with a project in hand
            # should pass it.
            cur = self._conn.execute("SELECT * FROM work_items WHERE external_id = ?", (external_id,))
        else:
            raise ValueError("get_work_item requires id, or external_id (optionally with project_code)")
        return _row_to_dict(cur.fetchone(), self._WORK_ITEM_JSON_FIELDS)

    def list_work_items(
        self,
        project_code: str | None = None,
        state: str | None = None,
        module: str | None = None,
        parent: str | None = None,
    ) -> list[dict]:
        clauses = []
        params: list[Any] = []
        if project_code is not None:
            clauses.append("project_code = ?")
            params.append(project_code)
        if state is not None:
            clauses.append("state = ?")
            params.append(state)
        if module is not None:
            clauses.append("module_id = ?")
            params.append(module)
        if parent is not None:
            clauses.append("parent_work_item_id = ?")
            params.append(parent)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = self._conn.execute(f"SELECT * FROM work_items {where} ORDER BY created_at", params)
        return [_row_to_dict(r, self._WORK_ITEM_JSON_FIELDS) for r in cur.fetchall()]

    def set_work_item_state(self, id: str, state: str, completed_by: str | None = None) -> dict:
        _validate_enum(state, WORK_ITEM_STATES, "state")
        now = _now()
        completed_at = now if state == "done" else None
        self._conn.execute(
            """
            UPDATE work_items
            SET state = ?, updated_at = ?, completed_at = ?, completed_by = ?
            WHERE id = ?
            """,
            (state, now, completed_at, completed_by, id),
        )
        self._conn.commit()
        return self.get_work_item(id=id)

    # ── work_item_relations ──────────────────────────────────────────────────

    def add_relation(
        self, project_code: str, work_item_id: str, related_work_item_id: str,
        relation_type: str, idempotency_key: str | None = None,
    ) -> dict:
        _validate_enum(relation_type, RELATION_TYPES, "relation_type")
        row_id = _new_id()
        self._conn.execute(
            """
            INSERT INTO work_item_relations
                (id, project_code, work_item_id, related_work_item_id, relation_type, idempotency_key)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (row_id, project_code, work_item_id, related_work_item_id, relation_type, idempotency_key),
        )
        self._conn.commit()
        cur = self._conn.execute("SELECT * FROM work_item_relations WHERE id = ?", (row_id,))
        return _row_to_dict(cur.fetchone())

    def remove_relation(self, work_item_id: str, related_work_item_id: str, relation_type: str) -> None:
        self._conn.execute(
            """
            DELETE FROM work_item_relations
            WHERE work_item_id = ? AND related_work_item_id = ? AND relation_type = ?
            """,
            (work_item_id, related_work_item_id, relation_type),
        )
        self._conn.commit()

    def list_relations(self, work_item: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM work_item_relations WHERE work_item_id = ? OR related_work_item_id = ?",
            (work_item, work_item),
        )
        return [_row_to_dict(r) for r in cur.fetchall()]

    # ── cycles ───────────────────────────────────────────────────────────────

    def upsert_cycle(self, project_code: str, external_id: str, **fields: Any) -> dict:
        _validate_enum(fields.get("state"), LIFECYCLE_STATES, "state")
        existing = self._get_cycle_row(project_code, external_id)
        row = {
            "id": (existing or {}).get("id") or fields.get("id") or _new_id(),
            "external_id": external_id,
            "project_code": project_code,
            "name": fields.get("name", (existing or {}).get("name")),
            "description": fields.get("description", (existing or {}).get("description")),
            "state": fields.get("state", (existing or {}).get("state")),
            "start_date": fields.get("start_date", (existing or {}).get("start_date")),
            "end_date": fields.get("end_date", (existing or {}).get("end_date")),
        }
        self._conn.execute(
            """
            INSERT INTO cycles (id, external_id, project_code, name, description, state, start_date, end_date)
            VALUES (:id, :external_id, :project_code, :name, :description, :state, :start_date, :end_date)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, description=excluded.description, state=excluded.state,
                start_date=excluded.start_date, end_date=excluded.end_date
            """,
            row,
        )
        self._conn.commit()
        return self._get_cycle_row(project_code, external_id)

    def _get_cycle_row(self, project_code: str, external_id: str) -> dict | None:
        cur = self._conn.execute(
            "SELECT * FROM cycles WHERE project_code = ? AND external_id = ?",
            (project_code, external_id),
        )
        return _row_to_dict(cur.fetchone())

    def assign_cycle(self, cycle_id: str, work_item_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO cycle_assignments (cycle_id, work_item_id) VALUES (?, ?)",
            (cycle_id, work_item_id),
        )
        self._conn.commit()

    def unassign_cycle(self, cycle_id: str, work_item_id: str) -> None:
        self._conn.execute(
            "DELETE FROM cycle_assignments WHERE cycle_id = ? AND work_item_id = ?",
            (cycle_id, work_item_id),
        )
        self._conn.commit()

    def list_cycles(self, project_code: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM cycles WHERE project_code = ? ORDER BY external_id", (project_code,)
        )
        return [_row_to_dict(r) for r in cur.fetchall()]

    # ── initiatives ──────────────────────────────────────────────────────────

    def upsert_initiative(self, external_id: str, **fields: Any) -> dict:
        _validate_enum(fields.get("state"), LIFECYCLE_STATES, "state")
        existing = self.get_initiative(external_id=external_id)
        row = {
            "id": (existing or {}).get("id") or fields.get("id") or _new_id(),
            "external_id": external_id,
            "title": fields.get("title", (existing or {}).get("title")),
            "description": fields.get("description", (existing or {}).get("description")),
            "state": fields.get("state", (existing or {}).get("state")),
            "doc_paths": _dump(fields.get("doc_paths", (existing or {}).get("doc_paths") or [])),
        }
        self._conn.execute(
            """
            INSERT INTO initiatives (id, external_id, title, description, state, doc_paths)
            VALUES (:id, :external_id, :title, :description, :state, :doc_paths)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, description=excluded.description,
                state=excluded.state, doc_paths=excluded.doc_paths
            """,
            row,
        )
        self._conn.commit()
        return self.get_initiative(external_id=external_id)

    def get_initiative(self, id: str | None = None, external_id: str | None = None) -> dict | None:
        if id is not None:
            cur = self._conn.execute("SELECT * FROM initiatives WHERE id = ?", (id,))
        elif external_id is not None:
            cur = self._conn.execute("SELECT * FROM initiatives WHERE external_id = ?", (external_id,))
        else:
            raise ValueError("get_initiative requires id or external_id")
        return _row_to_dict(cur.fetchone(), ["doc_paths"])

    def list_initiatives(self) -> list[dict]:
        cur = self._conn.execute("SELECT * FROM initiatives ORDER BY external_id")
        return [_row_to_dict(r, ["doc_paths"]) for r in cur.fetchall()]

    def link_initiative(self, initiative_id: str, link_type: str, target: str) -> None:
        _validate_enum(link_type, LINK_TYPES, "link_type")
        self._conn.execute(
            "INSERT OR IGNORE INTO initiative_links (initiative_id, link_type, target) VALUES (?, ?, ?)",
            (initiative_id, link_type, target),
        )
        self._conn.commit()

    def unlink_initiative(self, initiative_id: str, link_type: str, target: str) -> None:
        self._conn.execute(
            "DELETE FROM initiative_links WHERE initiative_id = ? AND link_type = ? AND target = ?",
            (initiative_id, link_type, target),
        )
        self._conn.commit()

    def list_initiative_links(self, initiative: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM initiative_links WHERE initiative_id = ?", (initiative,)
        )
        return [_row_to_dict(r) for r in cur.fetchall()]

    # ── worklog ──────────────────────────────────────────────────────────────

    def append_worklog(self, author: str, summary: str, **fields: Any) -> dict:
        row_id = fields.get("id") or _new_id()
        row = {
            "id": row_id,
            "author": author,
            "project": fields.get("project"),
            "summary": summary,
            "detailed": fields.get("detailed"),
            "tags": _dump(fields.get("tags") or []),
            "client": fields.get("client"),
            "surface": fields.get("surface"),
            "work_item_id": fields.get("work_item_id"),
            "created_at": fields.get("created_at") or _now(),
        }
        self._conn.execute(
            """
            INSERT INTO worklog (id, author, project, summary, detailed, tags, client, surface, work_item_id, created_at)
            VALUES (:id, :author, :project, :summary, :detailed, :tags, :client, :surface, :work_item_id, :created_at)
            """,
            row,
        )
        self._conn.commit()
        cur = self._conn.execute("SELECT * FROM worklog WHERE id = ?", (row_id,))
        return _row_to_dict(cur.fetchone(), ["tags"])

    def recent_worklog(self, limit: int = 10) -> list[dict]:
        cur = self._conn.execute("SELECT * FROM worklog ORDER BY created_at DESC LIMIT ?", (limit,))
        return [_row_to_dict(r, ["tags"]) for r in cur.fetchall()]

    def search_worklog(
        self,
        project: str | None = None,
        author: str | None = None,
        tags: list[str] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict]:
        clauses = []
        params: list[Any] = []
        if project is not None:
            clauses.append("project = ?")
            params.append(project)
        if author is not None:
            clauses.append("author = ?")
            params.append(author)
        if from_date is not None:
            clauses.append("created_at >= ?")
            params.append(from_date)
        if to_date is not None:
            clauses.append("created_at <= ?")
            params.append(to_date)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = self._conn.execute(f"SELECT * FROM worklog {where} ORDER BY created_at DESC", params)
        rows = [_row_to_dict(r, ["tags"]) for r in cur.fetchall()]
        if tags:
            wanted = set(tags)
            rows = [r for r in rows if wanted.intersection(r.get("tags") or [])]
        return rows

    # ── verifier_runs ────────────────────────────────────────────────────────

    def record_verifier_run(self, external_id: str, project_code: str, **fields: Any) -> dict:
        row_id = fields.get("id") or _new_id()
        row = {
            "id": row_id,
            "external_id": external_id,
            "project_code": project_code,
            "started_at": fields.get("started_at") or _now(),
            "finished_at": fields.get("finished_at"),
            "outcome": fields.get("outcome"),
            "judge": fields.get("judge"),
            "steps": _dump(fields.get("steps")),
            "error": fields.get("error"),
        }
        self._conn.execute(
            """
            INSERT INTO verifier_runs (id, external_id, project_code, started_at, finished_at, outcome, judge, steps, error)
            VALUES (:id, :external_id, :project_code, :started_at, :finished_at, :outcome, :judge, :steps, :error)
            ON CONFLICT(id) DO UPDATE SET
                finished_at=excluded.finished_at, outcome=excluded.outcome,
                judge=excluded.judge, steps=excluded.steps, error=excluded.error
            """,
            row,
        )
        self._conn.commit()
        return self.get_verifier_run(row_id)

    def get_verifier_run(self, id: str) -> dict | None:
        cur = self._conn.execute("SELECT * FROM verifier_runs WHERE id = ?", (id,))
        return _row_to_dict(cur.fetchone(), ["steps"])

    # ── filings (append-only) ────────────────────────────────────────────────

    def add_filing(self, external_id: str, project_code: str, idempotency_key: str, candidate: dict) -> str:
        """Insert a new, immutable filing row. Returns the new `filing_id`.

        Sets the corresponding `work_items` row's `acceptance_criteria_ref` to
        point at this filing, if that row already exists — a filing for a work
        item not yet upserted is legal (the tools row files then upserts, or
        vice versa); it simply has nothing to update yet.

        No update/delete method exists on `Store` for this table, by design —
        each filing is the work item's shape frozen at the moment it was filed.
        """
        filing_id = _new_id()
        acceptance_criteria = candidate.get("acceptance_criteria")
        row = {
            "id": filing_id,
            "external_id": external_id,
            "project_code": project_code,
            "idempotency_key": idempotency_key,
            "candidate_json": json.dumps(candidate),
            "acceptance_criteria_json": _dump(acceptance_criteria),
            "filed_at": _now(),
        }
        self._conn.execute(
            """
            INSERT INTO filings (id, external_id, project_code, idempotency_key,
                candidate_json, acceptance_criteria_json, filed_at)
            VALUES (:id, :external_id, :project_code, :idempotency_key,
                :candidate_json, :acceptance_criteria_json, :filed_at)
            """,
            row,
        )
        ref = f"graph://filing/{filing_id}/item/{external_id}#acceptance_criteria"
        self._conn.execute(
            "UPDATE work_items SET acceptance_criteria_ref = ? WHERE project_code = ? AND external_id = ?",
            (ref, project_code, external_id),
        )
        self._conn.commit()
        return filing_id

    def get_filing(self, filing_id: str) -> dict | None:
        cur = self._conn.execute("SELECT * FROM filings WHERE id = ?", (filing_id,))
        return _row_to_dict(cur.fetchone(), ["acceptance_criteria_json"])

    def latest_filing(self, external_id: str) -> dict | None:
        cur = self._conn.execute(
            "SELECT * FROM filings WHERE external_id = ? ORDER BY filed_at DESC LIMIT 1",
            (external_id,),
        )
        return _row_to_dict(cur.fetchone(), ["acceptance_criteria_json"])

    def resolve_criteria(self, ref: str) -> list[dict]:
        """Parses `graph://filing/<filing_id>/item/<external_id>#acceptance_criteria`
        and returns the criteria list recorded on that filing."""
        prefix = "graph://filing/"
        if not ref.startswith(prefix):
            raise ValueError(f"not a filing ref: {ref!r}")
        rest = ref[len(prefix):]
        filing_id, _, tail = rest.partition("/item/")
        if not filing_id or not tail:
            raise ValueError(f"malformed filing ref: {ref!r}")
        filing = self.get_filing(filing_id)
        if filing is None:
            raise ValueError(f"no such filing: {filing_id!r}")
        return filing["acceptance_criteria_json"] or []
