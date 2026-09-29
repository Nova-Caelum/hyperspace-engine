"""hooks/session_start.py — the Python half of the SessionStart hook.

`hooks/session-start.sh` prints the primer and the setup-state line (work
that must succeed with no Python at all), finds an interpreter, and runs:

    <python> hooks/session_start.py <project_dir> <plugin_root> <source>

This renders the active-loop-run block (with the T3.6 startup/compact budget
bump folded in) and the recent-worklog block, both against the project the
session opened in. Stdlib only — it runs before the project's environment
exists — plus this plugin's own `bin/loop_state.py`. Every exception is caught
locally so one bad run folder, one unreadable config, or a database error
degrades that one block rather than the whole hook — see the module docstring
in bin/loop_state.py for the verbs this calls (`bump`, `notify`) and
hyperspace/store/schema.sql for the `worklog` table shape this reads directly
(a coupling named in docs/reference/tripwires.md).

Every field printed from `loop.state.json` or the local task graph is
field-selective (an enum, a count, or a validated slug) — never a free-text
field such as `original_input` or a worklog's `detailed` body
(hook-secret-handling discipline: hook stdout is model input and is
prompt-injection-reachable).
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_BUMP_EVENTS = ("startup", "compact")
_DEFAULT_TERMINAL = {"done", "descoped", "killed"}


def _safe_field(value) -> str:
    """A field pulled from loop.state.json is model input reaching hook
    stdout — never print it unless it is a short enum-shaped token."""
    if isinstance(value, str) and _SLUG_RE.match(value):
        return value
    return "unknown"


def _loop_modules(plugin_root: Path):
    """`(loop_state, terminal_statuses)` from this plugin's own `bin/`, or
    `(None, defaults)` when those modules cannot be imported."""
    bin_dir = str(plugin_root / "bin")
    if bin_dir not in sys.path:
        sys.path.insert(0, bin_dir)
    try:
        import loop_state
        import loop_terminal

        return loop_state, set(loop_terminal.LEGITIMATE_TERMINAL)
    except Exception:
        return None, set(_DEFAULT_TERMINAL)


def active_runs(project_dir: Path, plugin_root: Path, source: str) -> list[str]:
    """One status line per non-terminal run under `<project>/hyperspace/runs`,
    each followed by any budget notify lines — bumping `fresh_sessions` /
    `compactions` first when `source` is `startup` / `compact`."""
    loop_state, terminal = _loop_modules(plugin_root)
    lines: list[str] = []
    runs_dir = project_dir / "hyperspace" / "runs"
    if not runs_dir.is_dir():
        return lines
    for state_path in sorted(runs_dir.glob("*/loop.state.json")):
        try:
            if loop_state is not None:
                state = loop_state.LoopState.load(state_path)
                data = state.data
            else:
                state = None
                data = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if data.get("status") in terminal:
            continue

        notify_lines: list[str] = []
        if state is not None and source in _BUMP_EVENTS:
            try:
                loop_state.bump(state, event=source)
                notify_lines = loop_state.notify(state)
            except Exception:
                notify_lines = []

        gates_passed = sum(
            1 for g in (data.get("gates") or [])
            if isinstance(g, dict) and g.get("passed") is True
        )
        lines.append(
            "goal=%s · status=%s · node=%s · gates_passed=%d"
            % (
                _safe_field(data.get("goal_slug")),
                _safe_field(data.get("status")),
                _safe_field(data.get("current_node")),
                gates_passed,
            )
        )
        lines.extend(notify_lines)
    return lines


def _worklog_owner(hyperspace_dir: Path) -> str:
    """`worklog_owner` (default "hyperspace-engine"): a config.toml key this
    hook alone reads. hyperspace/config.py's Config dataclass has no field for
    it and never will need one — an unrecognized key in a flat TOML file is
    inert to every other reader, and load_config() only ever `.get()`s the
    keys it knows. Lets a future integration that owns its own worklog
    display opt this block off without editing this hook."""
    owner = "hyperspace-engine"
    config_path = hyperspace_dir / "config.toml"
    if config_path.is_file():
        try:
            import tomllib

            with config_path.open("rb") as fh:
                cfg = tomllib.load(fh)
            raw_owner = cfg.get("worklog_owner")
            if isinstance(raw_owner, str) and raw_owner.strip():
                owner = raw_owner.strip()
        except Exception:
            pass
    return owner


def recent_worklog(project_dir: Path) -> list[str]:
    """Up to five `date | author | summary` lines, newest first — or nothing
    when the store is absent or another owner has claimed the worklog block
    (owner-yield)."""
    hyperspace_dir = project_dir / ".hyperspace"
    graph_db = hyperspace_dir / "graph.db"
    if not graph_db.is_file() or _worklog_owner(hyperspace_dir) != "hyperspace-engine":
        return []
    try:
        conn = sqlite3.connect(f"{graph_db.resolve().as_uri()}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT created_at, author, summary FROM worklog "
                "ORDER BY created_at DESC LIMIT 5"
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    lines: list[str] = []
    for created_at, author, summary in rows:
        date = created_at[:10] if isinstance(created_at, str) else ""
        author_s = author if isinstance(author, str) else ""
        # Store already caps summary at 280 chars on write
        # (hyperspace/tools/reads.py); re-cap defensively so a row inserted
        # by any other path can never blow the hook's own output budget.
        summary_s = summary[:280] if isinstance(summary, str) else ""
        lines.append("- %s | %s | %s" % (date, author_s, summary_s))
    return lines


def render(project_dir: Path, plugin_root: Path, source: str) -> str:
    """The whole Python half of the hook's output, as one string."""
    out: list[str] = []
    runs = active_runs(project_dir, plugin_root, source)
    if runs:
        out += ["## Active loop", *runs, ""]
    worklog = recent_worklog(project_dir)
    if worklog:
        out += ["## Recent worklog", *worklog, ""]
    return "\n".join(out) + ("\n" if out else "")


def main(argv: list[str]) -> int:
    # Hook stdout is decoded as UTF-8; a Windows pipe would otherwise be
    # written in the ANSI code page (`·` as 0xB7, `→` unencodable).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        project_dir, plugin_root, source = Path(argv[0]), Path(argv[1]), argv[2]
        sys.stdout.write(render(project_dir, plugin_root, source))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
