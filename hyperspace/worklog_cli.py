"""hyperspace/worklog_cli.py — `hyperspace worklog append|recent|search|
import|mirror` (v0.1.2 brief, worklog-cli-mirror row).

A sibling plugin's MCP server cannot call this plugin's MCP tools, so this
module is the CLI contract it shells out to instead — runnable as
`.hyperspace/env/bin/python -m hyperspace.cli worklog …` or the installed
`hyperspace` entrypoint. Every verb takes `--json` (structured stdout) and
`--dir <project>` (default cwd).

Exit codes: 0 ok · 2 usage/validation · 3 store missing (no
`.hyperspace/graph.db`). Every non-zero exit prints one JSON object
`{"ok": false, "error": ...}` to stdout when `--json` was passed — the same
single channel `{"ok": true, ...}` uses on success, so a caller only ever
reads one stream. A schema-version mismatch this build's own migration
cannot resolve, or any other unexpected internal error, exits 1 — outside
this contract's three pinned codes; see `docs/reference/tripwires.md`.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .store import SchemaVersionError, Store
from .store.worklog_mirror import rebuild_mirror, read_config_str

_ENTRY_FIELDS = (
    "id", "created_at", "author", "project", "summary", "detailed", "tags", "work_item_id",
)
_DEFAULT_PROJECT_FALLBACK = "workspace"
_SUMMARY_MAX = 280


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hyperspace worklog", add_help=False)
    subparsers = parser.add_subparsers(dest="verb", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--dir", default=".", help="project directory (default cwd)")
        p.add_argument("--json", action="store_true", help="emit one JSON object on stdout")

    p_append = subparsers.add_parser("append", add_help=False, help="append one worklog row")
    _common(p_append)
    p_append.add_argument("--author", required=True)
    p_append.add_argument("--summary", required=True)
    p_append.add_argument("--project", default=None, help="default: config key worklog_default_project, or 'workspace'")
    p_append.add_argument("--detail", default=None)
    p_append.add_argument("--tags", default=None, help="comma-separated")
    p_append.add_argument("--work-item-id", dest="work_item_id", default=None)

    p_recent = subparsers.add_parser("recent", add_help=False, help="most recent rows, newest first")
    _common(p_recent)
    p_recent.add_argument("--limit", type=int, default=10)

    p_search = subparsers.add_parser("search", add_help=False, help="filter rows")
    _common(p_search)
    p_search.add_argument("--project", default=None)
    p_search.add_argument("--author", default=None)
    p_search.add_argument("--tags", default=None, help="comma-separated, any-match")
    p_search.add_argument("--from", dest="from_date", default=None)
    p_search.add_argument("--to", dest="to_date", default=None)
    p_search.add_argument("--query", default=None, help="substring match on summary/detailed")

    p_import = subparsers.add_parser("import", add_help=False, help="import a sibling plugin's markdown entries")
    _common(p_import)
    p_import.add_argument("--from", dest="from_dir", required=True)

    p_mirror = subparsers.add_parser("mirror", add_help=False, help="re-render the store-side markdown mirror")
    _common(p_mirror)
    p_mirror.add_argument("--rebuild", action="store_true")

    return parser


def _ok(payload: dict) -> dict:
    return {"ok": True, **payload}


def _err(message: str) -> dict:
    return {"ok": False, "error": message}


def _print(json_mode: bool, payload: dict, human: str) -> None:
    print(json.dumps(payload) if json_mode else human)


def _db_path(project_dir: Path) -> Path:
    return project_dir / ".hyperspace" / "graph.db"


def _resolve_default_project(store: Store, project_dir: Path) -> str:
    code = read_config_str(project_dir, "worklog_default_project") or _DEFAULT_PROJECT_FALLBACK
    if store.get_project(code) is None:
        store.upsert_project(code=code, name=code)
    return code


def _entry_view(row: dict) -> dict:
    return {k: row.get(k) for k in _ENTRY_FIELDS}


def _split_tags(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    return [t.strip() for t in raw.split(",") if t.strip()]


# ── a sibling plugin's own frontmatter format (read-only reference; this
# module never imports that plugin's code) ──────────────────────────────

def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """`key: value` lines between a leading `---`/`---` pair, JSON-decoding
    any value that looks like a JSON string or list — the same shape a
    sibling plugin's own worklog writer produces. Returns `(meta, body)`;
    `meta` is `{}` for a file carrying no frontmatter block."""
    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if value.startswith('"') or value.startswith("["):
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        pass
                meta[key] = value
            body = text[end + 4:].lstrip("\n")
    return meta, body


def _normalize_import_date(value: str) -> str:
    """The borrowed format writes `%Y-%m-%dT%H:%M:%SZ`; normalize to this
    store's own `isoformat()` shape so imported and natively-written rows
    sort consistently by `created_at`."""
    try:
        dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        return value


# ── verbs ────────────────────────────────────────────────────────────────

def _verb_append(store: Store, project_dir: Path, args: argparse.Namespace) -> tuple[int, dict, str]:
    if len(args.summary) > _SUMMARY_MAX:
        return 2, _err(f"summary exceeds {_SUMMARY_MAX} characters (got {len(args.summary)})"), ""

    work_item_id = args.work_item_id
    if work_item_id is not None and store.get_work_item(id=work_item_id) is None:
        return 2, _err(f"no such work item: {work_item_id!r}"), ""

    project = args.project or _resolve_default_project(store, project_dir)
    row = store.append_worklog(
        author=args.author, summary=args.summary, project=project,
        detailed=args.detail, tags=_split_tags(args.tags) or [], work_item_id=work_item_id,
    )
    entry = _entry_view(row)
    return 0, _ok({"entry": entry}), f"appended {entry['id']}: {entry['summary']}"


def _verb_recent(store: Store, project_dir: Path, args: argparse.Namespace) -> tuple[int, dict, str]:
    rows = store.recent_worklog(limit=args.limit)
    return 0, _ok({"entries": rows}), f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}"


def _verb_search(store: Store, project_dir: Path, args: argparse.Namespace) -> tuple[int, dict, str]:
    rows = store.search_worklog(
        project=args.project, author=args.author, tags=_split_tags(args.tags),
        from_date=args.from_date, to_date=args.to_date, query=args.query,
    )
    return 0, _ok({"entries": rows}), f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}"


def _verb_import(store: Store, project_dir: Path, args: argparse.Namespace) -> tuple[int, dict, str]:
    source_dir = Path(args.from_dir)
    if not source_dir.is_absolute():
        source_dir = (project_dir / source_dir).resolve()
    if not source_dir.is_dir():
        return 2, _err(f"no such directory: {source_dir}"), ""

    project = _resolve_default_project(store, project_dir)
    imported = 0
    skipped = 0
    for path in sorted(source_dir.glob("*.md")):
        source_file = path.name
        if store.get_worklog_by_source_file(source_file) is not None:
            skipped += 1
            continue
        try:
            meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
            author = meta.get("author")
            summary = meta.get("summary")
            if not isinstance(author, str) or not isinstance(summary, str):
                skipped += 1
                continue
            tags = meta.get("tags")
            tags = tags if isinstance(tags, list) else []
            created_at = _normalize_import_date(meta["date"]) if isinstance(meta.get("date"), str) else None
            store.append_worklog(
                author=author, summary=summary[:_SUMMARY_MAX], project=project,
                detailed=body or None, tags=tags, created_at=created_at, source_file=source_file,
            )
            imported += 1
        except Exception:
            skipped += 1
    return 0, _ok({"imported": imported, "skipped": skipped}), f"imported {imported}, skipped {skipped}"


def _verb_mirror(store: Store, project_dir: Path, args: argparse.Namespace) -> tuple[int, dict, str]:
    if not args.rebuild:
        return 2, _err("mirror requires --rebuild"), ""
    rendered, skipped = rebuild_mirror(store.search_worklog(), _db_path(project_dir))
    return 0, _ok({"rendered": rendered, "skipped": skipped}), f"rendered {rendered}, skipped {skipped}"


_VERBS: dict[str, Callable[[Store, Path, argparse.Namespace], tuple[int, dict, str]]] = {
    "append": _verb_append, "recent": _verb_recent, "search": _verb_search,
    "import": _verb_import, "mirror": _verb_mirror,
}


def main(argv: list[str]) -> int:
    parser = build_parser()
    json_requested = "--json" in argv
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
        if json_requested:
            print(json.dumps(_err("usage error — see stderr")))
        return code

    project_dir = Path(args.dir).resolve()
    db_path = _db_path(project_dir)
    if not db_path.is_file():
        message = f"no {db_path} — run `hyperspace init` first"
        _print(args.json, _err(message), message)
        return 3

    try:
        store = Store.open(db_path)
    except (SchemaVersionError, sqlite3.OperationalError) as exc:
        # A schema mismatch this build's own migration can't resolve, or a
        # transient open-time failure (e.g. the db locked by a concurrent
        # writer mid-migration) — either way, this contract's stdout stays
        # one JSON object; the traceback is never the caller's problem.
        _print(args.json, _err(str(exc)), str(exc))
        return 1

    try:
        code, payload, human = _VERBS[args.verb](store, project_dir, args)
    except Exception as exc:  # noqa: BLE001 — never let an internal error crash the CLI contract
        code, payload, human = 1, _err(f"{type(exc).__name__}: {exc}"), f"error: {exc}"
    finally:
        store.close()

    _print(args.json, payload, human)
    return code
