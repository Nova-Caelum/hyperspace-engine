-- hyperspace/store/schema.sql — the product's local SQLite database (row T2.1).
--
-- Column names are copied VERBATIM from the console — never redesigned. Source:
-- `~/NovaCaelum_code/Caelos-foundry`, checked out at `origin/main`, file
-- `src/app/App.tsx`. Two kinds of evidence were used:
--   (1) the FE `type` declarations (what the console's components consume), and
--   (2) the `adapt*Read` functions (what the console's fetch layer actually reads
--       off the wire — `x.<field>` — which is the true backend column name; the FE
--       type name is sometimes a renamed/derived view of it, e.g. `WorkItem.title`
--       reads backend `x.name`, `WorkItem.assignee` reads backend `x.assignee_agent`).
-- Where the two disagree, the backend name (2) is what this schema stores, because
-- this file IS the backend. FE-only derived/renamed fields (`WorkItem.title`,
-- `.priority`, `.assignee`, `.blocked_by`, `.doc_paths`, `.cycle_id`,
-- `.parent_item_id`, `.uuid`, `.project_id`) are not separate backend columns —
-- they are the adapter's view, not storage.
--
-- Line citations (App.tsx @ origin/main):
--   Project             type   L27   adaptProjectRead      L274-284
--   Mod (module)        type   L38   adaptModuleRead       L321-336
--   Cycle               type   L39   adaptCycleRead        L338-347
--   WorkItem            type   L43-49 adaptWorkItemRead    L287-320
--   Initiative          type   L55   adaptInitiativeRead   L349-358
--   WorklogEntry        type   L59   (no adapter — read via MCP `get_recent_activity`,
--                                     shape is verbatim; also SR#3 worklog discipline)
--   Agent               type   L62   (advisory only — not a Store table, per brief §3b)
--
-- `work_items` columns are the closed, authoritative list handed down in the Plan/PRD
-- (T2.1 step 4's sample row) — this is the backend's own shape, which is a superset in
-- some places (type, effort_level, tags, added_by, idempotency_key, updated_at,
-- completed_at, completed_by, uncertainty_notes — all consumed by the loop/tools layer,
-- not by this console view) and does not include the FE-derived fields named above.
--
-- `projects` carries BOTH `code` (PK — what the REST routes key on, and what
-- `adaptProjectRead` prefers as `x.code ?? x.id`) and `id` (a separate uuid) — both
-- appear as real backend columns per the Plan's sample row for `projects`.
--
-- List-shaped fields (`team`, `doc_paths`, `tags`, `source_references`,
-- `uncertainty_notes`) are stored as JSON text and decoded on read by `Store`.
--
-- Enum-shaped fields (`state`, `status`, `relation_type`, `link_type`) are validated in
-- `Store`, not via SQL CHECK constraints, so a future value-set migration is one file.
--
-- `PRAGMA foreign_keys = ON` and `PRAGMA journal_mode = WAL` are set per-connection by
-- `Store.__init__` (WAL persists once set; foreign_keys does not — SQLite requires it
-- on every connection). Timestamps are UTC ISO-8601 strings, written by `Store`.
--
-- `worklog.source_file` (v0.1.2, nullable): the filename of the markdown row this
-- worklog entry was imported from, when it was imported rather than written natively.
-- An existing v0.1.1 db gains this column via `Store`'s own idempotent migration on
-- next open — never a hand-run script. Set, it means: never re-render this row into
-- the store-side markdown mirror (the source file already exists on disk).

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE projects (
    code        TEXT PRIMARY KEY,
    id          TEXT NOT NULL,
    name        TEXT,
    description TEXT,
    status      TEXT,
    parent_code TEXT,
    owner       TEXT,
    client      TEXT,
    next_action TEXT,
    folder_path TEXT,
    team        TEXT,
    created_at  TEXT,
    updated_at  TEXT
);

CREATE TABLE modules (
    id                      TEXT PRIMARY KEY,
    external_id             TEXT NOT NULL,
    project_code            TEXT NOT NULL REFERENCES projects(code),
    name                    TEXT,
    description             TEXT,
    state                   TEXT,
    parent_module_id        TEXT REFERENCES modules(id),
    folder_path             TEXT,
    team                    TEXT,
    acceptance_criteria     TEXT,
    acceptance_criteria_ref TEXT,
    created_at              TEXT,
    updated_at              TEXT,
    UNIQUE (project_code, external_id)
);

CREATE TABLE work_items (
    id                      TEXT PRIMARY KEY,
    external_id             TEXT NOT NULL,
    project_code            TEXT NOT NULL REFERENCES projects(code),
    name                    TEXT,
    type                    TEXT,
    state                   TEXT,
    module_id               TEXT REFERENCES modules(id),
    parent_work_item_id     TEXT REFERENCES work_items(id),
    assignee_agent          TEXT,
    effort_level            TEXT,
    description             TEXT,
    source_references       TEXT,
    tags                    TEXT,
    added_by                TEXT,
    idempotency_key         TEXT,
    created_at              TEXT,
    updated_at              TEXT,
    completed_at            TEXT,
    team                    TEXT,
    acceptance_criteria     TEXT,
    acceptance_criteria_ref TEXT,
    position                REAL,
    completed_by            TEXT,
    uncertainty_notes       TEXT,
    UNIQUE (project_code, external_id)
);

CREATE TABLE work_item_relations (
    id                    TEXT PRIMARY KEY,
    project_code          TEXT NOT NULL REFERENCES projects(code),
    work_item_id          TEXT NOT NULL REFERENCES work_items(id),
    related_work_item_id  TEXT NOT NULL REFERENCES work_items(id),
    relation_type         TEXT NOT NULL,
    idempotency_key       TEXT
);

CREATE TABLE cycles (
    id            TEXT PRIMARY KEY,
    external_id   TEXT NOT NULL,
    project_code  TEXT NOT NULL REFERENCES projects(code),
    name          TEXT,
    description   TEXT,
    state         TEXT,
    start_date    TEXT,
    end_date      TEXT,
    UNIQUE (project_code, external_id)
);

CREATE TABLE cycle_assignments (
    cycle_id      TEXT NOT NULL REFERENCES cycles(id),
    work_item_id  TEXT NOT NULL REFERENCES work_items(id),
    PRIMARY KEY (cycle_id, work_item_id)
);

CREATE TABLE initiatives (
    id           TEXT PRIMARY KEY,
    external_id  TEXT NOT NULL UNIQUE,
    title        TEXT,
    description  TEXT,
    state        TEXT,
    doc_paths    TEXT
);

CREATE TABLE initiative_links (
    initiative_id  TEXT NOT NULL REFERENCES initiatives(id),
    link_type      TEXT NOT NULL,
    target         TEXT NOT NULL,
    PRIMARY KEY (initiative_id, link_type, target)
);

CREATE TABLE worklog (
    id            TEXT PRIMARY KEY,
    author        TEXT,
    project       TEXT,
    summary       TEXT,
    detailed      TEXT,
    tags          TEXT,
    client        TEXT,
    surface       TEXT,
    work_item_id  TEXT REFERENCES work_items(id),
    created_at    TEXT,
    source_file   TEXT
);

CREATE TABLE verifier_runs (
    id            TEXT PRIMARY KEY,
    external_id   TEXT,
    project_code  TEXT REFERENCES projects(code),
    started_at    TEXT,
    finished_at   TEXT,
    outcome       TEXT,
    judge         TEXT,
    steps         TEXT,
    error         TEXT
);

-- Append-only: no UPDATE/DELETE method exists on `Store` for this table. Each filing
-- is a work item's shape frozen at the moment it was filed, so the verifier can judge
-- against the criteria that existed at filing time — not whatever they later became.
CREATE TABLE filings (
    id                        TEXT PRIMARY KEY,
    external_id               TEXT NOT NULL,
    project_code              TEXT NOT NULL REFERENCES projects(code),
    idempotency_key           TEXT NOT NULL UNIQUE,
    candidate_json            TEXT NOT NULL,
    acceptance_criteria_json  TEXT,
    filed_at                  TEXT
);
