"""hyperspace/store/worklog_mirror.py — the store-side markdown mirror
(v0.1.2 brief, worklog-cli-mirror row).

A sibling plugin's own worklog format is markdown files with YAML-ish
frontmatter (`date`, `author`, `summary`, `tags`) under a directory it
manages. This engine cannot see or import that plugin's code (this plugin
must never detect it, per the joint plan this row is built against), but it
CAN render its own worklog rows into that same frontmatter shape, into a
directory the project owner names via one config key — `worklog_mirror_dir`
in `.hyperspace/config.toml`. This module is that renderer, plus the one
line this engine adds on top of the borrowed shape: `row_id`.

Derived and one-way: a render failure never blocks or reverts the insert
that triggered it — every public function here swallows its own exceptions
and returns a plain success/failure signal, never raises. Idempotent per
row: a row with `source_file` set (imported from that directory in the
first place) is never rendered — the original file already exists there,
often in this very mirror directory — and a row whose deterministic
filename already exists on disk is left alone, which is what lets
`hyperspace worklog mirror --rebuild` touch only what's missing.
"""
from __future__ import annotations

import json
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SLUG_MAX_LEN = 40


def project_dir_for(db_path: str | Path) -> Path:
    """The project root that owns `db_path` (`<project>/.hyperspace/graph.db`)
    — the same `.hyperspace`-parent convention `hyperspace/tools/reads.py`'s
    `list_agents` already relies on."""
    resolved = Path(db_path).resolve()
    if resolved.parent.name == ".hyperspace":
        return resolved.parent.parent
    return resolved.parent


def read_config_str(project_dir: str | Path, key: str) -> str | None:
    """Raw, selective `.hyperspace/config.toml` read for a key
    `hyperspace/config.py`'s `Config` dataclass does not (and will not) carry
    a field for — the same tolerant pattern `hooks/session-start.sh` already
    uses for `worklog_owner`: a missing file, an unreadable/malformed TOML
    file, or a missing/blank/non-string key all resolve to `None`."""
    config_path = Path(project_dir) / ".hyperspace" / "config.toml"
    if not config_path.is_file():
        return None
    try:
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
    except Exception:
        return None
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _slugify(text: str, max_len: int = _SLUG_MAX_LEN) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "entry"


def _parsed_created_at(created_at: str | None) -> datetime:
    if created_at:
        try:
            return datetime.fromisoformat(created_at)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _compact_timestamp(created_at: str | None) -> str:
    """`row["created_at"]` is this store's own `isoformat()` shape (or, for
    an imported row, already normalized to that shape by the CLI importer)
    — reformatted to the borrowed filename convention, `%Y%m%dT%H%M%SZ`."""
    return _parsed_created_at(created_at).strftime("%Y%m%dT%H%M%SZ")


def _frontmatter_date(created_at: str | None) -> str:
    return _parsed_created_at(created_at).strftime("%Y-%m-%dT%H:%M:%SZ")


def mirror_filename(row: dict) -> str:
    ts = _compact_timestamp(row.get("created_at"))
    slug = _slugify(row.get("summary") or "")
    short_id = str(row.get("id") or "")[:8]
    return f"{ts}-{slug}-{short_id}.md"


def render_markdown(row: dict) -> str:
    lines = [
        "---",
        f"date: {_frontmatter_date(row.get('created_at'))}",
        f"author: {json.dumps(row.get('author'))}",
        f"summary: {json.dumps(row.get('summary'))}",
        f"tags: {json.dumps(row.get('tags') or [])}",
        f"row_id: {json.dumps(row.get('id'))}",
        "---",
    ]
    body = row.get("detailed") or ""
    text = "\n".join(lines) + "\n" + body
    if body and not body.endswith("\n"):
        text += "\n"
    return text


def render_row(row: dict, db_path: str | Path) -> bool:
    """Renders one worklog row to the configured mirror directory. Returns
    True only when a new file was actually written — the signal
    `rebuild_mirror` uses to report `rendered` vs `skipped`. Never raises:
    a render failure must never block or revert the insert that triggered
    it (the brief's fix 1, condition a)."""
    try:
        if row.get("source_file"):
            return False
        project_dir = project_dir_for(db_path)
        mirror_dir_name = read_config_str(project_dir, "worklog_mirror_dir")
        if not mirror_dir_name:
            return False
        mirror_dir = project_dir / mirror_dir_name
        path = mirror_dir / mirror_filename(row)
        if path.exists():
            return False
        mirror_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(row), encoding="utf-8")
        return True
    except Exception:
        return False


def rebuild_mirror(rows: list[dict], db_path: str | Path) -> tuple[int, int]:
    """`hyperspace worklog mirror --rebuild` — re-renders every row missing
    its mirror file. Returns `(rendered, skipped)`; `skipped` covers every
    other reason a row didn't get a new file this pass (no mirror dir
    configured, imported, already present, or a swallowed render error)."""
    rendered = 0
    skipped = 0
    for row in rows:
        if render_row(row, db_path):
            rendered += 1
        else:
            skipped += 1
    return rendered, skipped
