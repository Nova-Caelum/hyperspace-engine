"""tests/test_worklog_cli.py — v0.1.2: `hyperspace worklog append|recent|
search|import|mirror`, the CLI contract a sibling plugin (unable to call this
plugin's MCP tools) shells out to instead, and the store-side markdown
mirror every worklog insert renders when `.hyperspace/config.toml` sets
`worklog_mirror_dir`.

Two invocation forms are load-bearing per the brief — `.hyperspace/env/bin/
python -m hyperspace.cli worklog …` and the installed `hyperspace`
entrypoint — so at least one subprocess test exercises each; the rest use
`cli.main([...])` in-process with `capsys` for speed.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hyperspace import cli
from hyperspace.store import Store

REPO_ROOT = Path(__file__).resolve().parents[1]


def _hyperspace_bin() -> Path:
    """The console script beside the running interpreter — `hyperspace` on
    POSIX, `hyperspace.exe` in a Windows venv's `Scripts/`."""
    name = "hyperspace.exe" if sys.platform == "win32" else "hyperspace"
    return Path(sys.executable).parent / name


def _venv_python() -> Path:
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def _run_module(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(_venv_python()), "-m", "hyperspace.cli", *args],
        capture_output=True, encoding="utf-8", errors="replace", cwd=REPO_ROOT,
    )


def _run_bin(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(_hyperspace_bin()), *args],
        capture_output=True, encoding="utf-8", errors="replace", cwd=REPO_ROOT,
    )


@pytest.fixture()
def project(tmp_path) -> Path:
    Store.init(tmp_path / ".hyperspace" / "graph.db").close()
    return tmp_path


def _write_config(project_dir: Path, text: str) -> None:
    (project_dir / ".hyperspace" / "config.toml").write_text(text, encoding="utf-8")


def _stdout_json(capsys) -> dict:
    out = capsys.readouterr().out.strip()
    assert out, "expected one line of JSON on stdout"
    return json.loads(out.splitlines()[-1])


def _tc_entry(entries_dir: Path, dt: datetime, slug: str, author: str, summary: str,
              tags: list[str], body: str = "") -> Path:
    """Writes one file in technical-cofounder's own worklog frontmatter
    format (read-only reference: its `worklog.py` `_render_frontmatter` /
    `append`) — never imported, reproduced here because this plugin must
    never import a sibling plugin's code."""
    entries_dir.mkdir(parents=True, exist_ok=True)
    fname_ts = dt.strftime("%Y%m%dT%H%M%SZ")
    date_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    path = entries_dir / f"{fname_ts}-{slug}.md"
    lines = [
        "---",
        f"date: {date_str}",
        f"author: {json.dumps(author)}",
        f"summary: {json.dumps(summary)}",
        f"tags: {json.dumps(tags)}",
        "---",
    ]
    text = "\n".join(lines) + "\n" + body
    if body and not body.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    return path


# ── append ───────────────────────────────────────────────────────────────


def test_append_json_shape_and_default_project(project, capsys):
    rc = cli.main(["worklog", "append", "--dir", str(project), "--author", "engineer",
                   "--summary", "Did a thing.", "--tags", "a,b", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out["ok"] is True
    entry = out["entry"]
    assert set(entry.keys()) == {
        "id", "created_at", "author", "project", "summary", "detailed", "tags", "work_item_id",
    }
    assert entry["author"] == "engineer"
    assert entry["summary"] == "Did a thing."
    assert entry["tags"] == ["a", "b"]
    assert entry["project"] == "workspace"
    assert entry["work_item_id"] is None
    assert entry["detailed"] is None

    store = Store.open(project / ".hyperspace" / "graph.db")
    try:
        assert store.get_project("workspace") is not None
    finally:
        store.close()


def test_append_default_project_from_config_key(project, capsys):
    _write_config(project, 'worklog_default_project = "my-project"\n')
    rc = cli.main(["worklog", "append", "--dir", str(project), "--author", "engineer",
                   "--summary", "Did a thing.", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out["entry"]["project"] == "my-project"

    store = Store.open(project / ".hyperspace" / "graph.db")
    try:
        assert store.get_project("my-project") is not None
    finally:
        store.close()


def test_append_explicit_project_used_verbatim(project, capsys):
    rc = cli.main(["worklog", "append", "--dir", str(project), "--author", "engineer",
                   "--summary", "x", "--project", "explicit-project", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out["entry"]["project"] == "explicit-project"


def test_append_summary_too_long_exits_2(project, capsys):
    rc = cli.main(["worklog", "append", "--dir", str(project), "--author", "engineer",
                   "--summary", "x" * 281, "--json"])
    assert rc == 2
    out = _stdout_json(capsys)
    assert out == {"ok": False, "error": "summary exceeds 280 characters (got 281)"}


def test_append_unknown_work_item_id_exits_2(project, capsys):
    rc = cli.main(["worklog", "append", "--dir", str(project), "--author", "engineer",
                   "--summary", "x", "--work-item-id", "does-not-exist", "--json"])
    assert rc == 2
    out = _stdout_json(capsys)
    assert out["ok"] is False


def test_append_with_known_work_item_id(project, capsys):
    store = Store.open(project / ".hyperspace" / "graph.db")
    try:
        store.upsert_project(code="demo-project", name="Demo")
        wi = store.upsert_work_item(
            project_code="demo-project", external_id="demo-project:wi-1",
            name="Do the thing", type="task", state="ready",
        )
        wi_id = wi["id"]
    finally:
        store.close()

    rc = cli.main(["worklog", "append", "--dir", str(project), "--author", "engineer",
                   "--summary", "Attached to a work item.", "--project", "demo-project",
                   "--work-item-id", wi_id, "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out["entry"]["work_item_id"] == wi_id


def test_missing_required_arg_exits_2_with_json_error(project, capsys):
    rc = cli.main(["worklog", "append", "--dir", str(project), "--summary", "x", "--json"])
    assert rc == 2
    out = _stdout_json(capsys)
    assert out["ok"] is False


# ── recent / search ──────────────────────────────────────────────────────


def test_recent_newest_first_json_shape(project, capsys):
    for i in range(3):
        cli.main(["worklog", "append", "--dir", str(project), "--author", "a",
                  "--summary", f"Entry {i}.", "--json"])
        capsys.readouterr()

    rc = cli.main(["worklog", "recent", "--dir", str(project), "--limit", "2", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out["ok"] is True
    assert [e["summary"] for e in out["entries"]] == ["Entry 2.", "Entry 1."]


def test_search_by_query_and_project(project, capsys):
    cli.main(["worklog", "append", "--dir", str(project), "--author", "a",
              "--project", "p1", "--summary", "Shipped the worklog CLI.", "--json"])
    capsys.readouterr()
    cli.main(["worklog", "append", "--dir", str(project), "--author", "a",
              "--project", "p2", "--summary", "Unrelated.", "--json"])
    capsys.readouterr()

    rc = cli.main(["worklog", "search", "--dir", str(project), "--project", "p1", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out["ok"] is True
    assert len(out["entries"]) == 1
    assert out["entries"][0]["summary"] == "Shipped the worklog CLI."

    rc = cli.main(["worklog", "search", "--dir", str(project), "--query", "worklog cli", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert len(out["entries"]) == 1
    assert out["entries"][0]["project"] == "p1"


# ── the store-side mirror ────────────────────────────────────────────────


def test_append_renders_mirror_file_with_exact_frontmatter(project, capsys):
    _write_config(project, 'worklog_mirror_dir = "worklog/entries"\n')
    rc = cli.main(["worklog", "append", "--dir", str(project), "--author", "engineer",
                   "--summary", "Shipped the CLI.", "--tags", "hsp-v012,worklog",
                   "--detail", "Full detail body.", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    row_id = out["entry"]["id"]

    files = list((project / "worklog" / "entries").glob("*.md"))
    assert len(files) == 1
    assert files[0].name.endswith(f"-{row_id[:8]}.md")
    text = files[0].read_text(encoding="utf-8")
    assert 'author: "engineer"' in text
    assert 'summary: "Shipped the CLI."' in text
    assert 'tags: ["hsp-v012", "worklog"]' in text
    assert f'row_id: "{row_id}"' in text
    assert text.rstrip("\n").endswith("Full detail body.")


def test_no_mirror_dir_created_without_config_key(project, capsys):
    rc = cli.main(["worklog", "append", "--dir", str(project), "--author", "engineer",
                   "--summary", "No mirror configured.", "--json"])
    assert rc == 0
    capsys.readouterr()
    assert not (project / "worklog").exists()


def test_forced_render_failure_does_not_block_the_insert(project, capsys):
    _write_config(project, 'worklog_mirror_dir = "blocked"\n')
    (project / "blocked").write_text("a file, not a directory", encoding="utf-8")

    rc = cli.main(["worklog", "append", "--dir", str(project), "--author", "engineer",
                   "--summary", "Still commits.", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out["ok"] is True

    store = Store.open(project / ".hyperspace" / "graph.db")
    try:
        entries = store.search_worklog(query="Still commits.")
        assert len(entries) == 1
    finally:
        store.close()


def test_mirror_rebuild_renders_missing_files_only(project, capsys):
    cli.main(["worklog", "append", "--dir", str(project), "--author", "a", "--summary", "One.", "--json"])
    capsys.readouterr()
    cli.main(["worklog", "append", "--dir", str(project), "--author", "a", "--summary", "Two.", "--json"])
    capsys.readouterr()

    _write_config(project, 'worklog_mirror_dir = "worklog/entries"\n')
    rc = cli.main(["worklog", "mirror", "--dir", str(project), "--rebuild", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out == {"ok": True, "rendered": 2, "skipped": 0}
    assert len(list((project / "worklog" / "entries").glob("*.md"))) == 2

    rc = cli.main(["worklog", "mirror", "--dir", str(project), "--rebuild", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out == {"ok": True, "rendered": 0, "skipped": 2}


def test_mirror_without_rebuild_flag_is_a_usage_error(project, capsys):
    rc = cli.main(["worklog", "mirror", "--dir", str(project), "--json"])
    assert rc == 2
    out = _stdout_json(capsys)
    assert out["ok"] is False


# ── import ───────────────────────────────────────────────────────────────


def test_import_idempotent_then_append_gives_n_plus_1_not_2n_plus_1(project, capsys):
    entries_dir = project / "worklog" / "entries"
    _tc_entry(entries_dir, datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
              "first-entry", "someone", "First TC entry.", ["a"])
    _tc_entry(entries_dir, datetime(2026, 9, 1, 12, 5, 0, tzinfo=timezone.utc),
              "second-entry", "someone", "Second TC entry.", ["b"], body="Body text.")
    _write_config(project, 'worklog_mirror_dir = "worklog/entries"\n')

    rc = cli.main(["worklog", "import", "--dir", str(project), "--from", "worklog/entries", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out == {"ok": True, "imported": 2, "skipped": 0}

    rc = cli.main(["worklog", "import", "--dir", str(project), "--from", "worklog/entries", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out == {"ok": True, "imported": 0, "skipped": 2}

    assert len(list(entries_dir.glob("*.md"))) == 2

    rc = cli.main(["worklog", "append", "--dir", str(project), "--author", "engineer",
                   "--summary", "Native HE entry.", "--json"])
    assert rc == 0
    capsys.readouterr()

    files = list(entries_dir.glob("*.md"))
    assert len(files) == 3

    store = Store.open(project / ".hyperspace" / "graph.db")
    try:
        rows = store.search_worklog()
        assert len(rows) == 3
        imported_rows = [r for r in rows if r.get("source_file")]
        assert len(imported_rows) == 2
        assert all(r["author"] == "someone" for r in imported_rows)
        native_rows = [r for r in rows if not r.get("source_file")]
        assert len(native_rows) == 1
        assert native_rows[0]["summary"] == "Native HE entry."
    finally:
        store.close()


def test_import_uses_default_project(project, capsys):
    entries_dir = project / "worklog" / "entries"
    _tc_entry(entries_dir, datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
              "an-entry", "someone", "A TC entry.", [])
    _write_config(project, 'worklog_default_project = "tc-project"\n')

    rc = cli.main(["worklog", "import", "--dir", str(project), "--from", "worklog/entries", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out == {"ok": True, "imported": 1, "skipped": 0}

    store = Store.open(project / ".hyperspace" / "graph.db")
    try:
        assert store.get_project("tc-project") is not None
        rows = store.search_worklog(project="tc-project")
        assert len(rows) == 1
        assert rows[0]["summary"] == "A TC entry."
    finally:
        store.close()


def test_import_missing_source_dir_exits_2(project, capsys):
    rc = cli.main(["worklog", "import", "--dir", str(project), "--from", "no/such/dir", "--json"])
    assert rc == 2
    out = _stdout_json(capsys)
    assert out["ok"] is False


# ── store missing / --dir default ───────────────────────────────────────


def test_store_missing_exits_3(tmp_path, capsys):
    rc = cli.main(["worklog", "recent", "--dir", str(tmp_path), "--json"])
    assert rc == 3
    out = _stdout_json(capsys)
    assert out["ok"] is False


def test_dir_defaults_to_cwd(project, capsys, monkeypatch):
    monkeypatch.chdir(project)
    rc = cli.main(["worklog", "append", "--author", "a", "--summary", "cwd default.", "--json"])
    assert rc == 0
    out = _stdout_json(capsys)
    assert out["ok"] is True


def test_open_lock_conflict_during_migration_is_clean_json_not_a_crash(tmp_path, capsys):
    """A v0.1.1-shaped db (schema_version=1) held under an EXCLUSIVE lock by
    a concurrent connection when `Store.open`'s migration tries to `ALTER
    TABLE` — this is a real `sqlite3.OperationalError`, not a
    `SchemaVersionError`, and the CLI must still answer with one clean JSON
    object and exit 1, never an uncaught traceback."""
    db_path = tmp_path / ".hyperspace" / "graph.db"
    db_path.parent.mkdir(parents=True)
    v1_schema = """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE worklog (
            id TEXT PRIMARY KEY, author TEXT, project TEXT, summary TEXT,
            detailed TEXT, tags TEXT, client TEXT, surface TEXT,
            work_item_id TEXT, created_at TEXT
        );
    """
    raw = sqlite3.connect(str(db_path))
    raw.executescript(v1_schema)
    raw.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1')")
    raw.commit()
    raw.close()

    locker = sqlite3.connect(str(db_path), timeout=0.1)
    locker.execute("BEGIN EXCLUSIVE")
    try:
        rc = cli.main(["worklog", "recent", "--dir", str(tmp_path), "--json"])
    finally:
        locker.rollback()
        locker.close()

    assert rc == 1
    out = _stdout_json(capsys)
    assert out["ok"] is False


# ── the two required invocation forms ───────────────────────────────────


def test_subprocess_module_invocation(project):
    result = _run_module(["worklog", "append", "--dir", str(project), "--author", "engineer",
                           "--summary", "Via python -m.", "--json"])
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip())
    assert out["ok"] is True
    assert out["entry"]["summary"] == "Via python -m."


def test_subprocess_hyperspace_entrypoint(project):
    hyperspace_bin = _hyperspace_bin()
    assert hyperspace_bin.exists(), f"expected console script at {hyperspace_bin}"
    result = _run_bin(["worklog", "append", "--dir", str(project), "--author", "engineer",
                       "--summary", "Via the hyperspace entrypoint.", "--json"])
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip())
    assert out["ok"] is True
    assert out["entry"]["summary"] == "Via the hyperspace entrypoint."
