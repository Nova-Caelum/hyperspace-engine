#!/bin/sh
# hooks/session-start.sh — primes the `acing-hyperspace` skill on every
# SessionStart. Wired unconditionally in hooks/hooks.json (no `matcher`), so
# this fires on every source Claude Code reports for the event — currently
# `startup`, `resume`, `clear`, `compact` and `fork` — rather than hard-coding
# the four this plugin's brief named and silently missing a fifth the next
# Claude Code release adds. Without this hook a compaction or `/clear` drops
# the loop silently: nothing re-primes the skill that routes a session to its
# run's station.
#
# POSIX sh only (no bash-only syntax) and no dependency beyond what the
# plugin already requires — Python 3.11+, no `jq`. `source` is pulled out of
# the SessionStart JSON on stdin with `sed`; frontmatter is stripped from the
# primer with `awk`. See docs/06_adaptation_notes.md §7 for what this ships
# relative to the source engine's own session-start hook, and
# docs/reference/tripwires.md for the couplings this script's literal names
# and paths create.
#
# Fail-open by construction: no `set -e`, and this script always exits 0 —
# SessionStart hooks are non-blocking in Claude Code, so a non-zero exit here
# would only hide a real failure from the transcript, never actually stop the
# session. Every field this script prints from `loop.state.json` or the local
# task graph is field-selective (an enum, a count, or a validated slug) —
# never a free-text field such as `original_input` or a worklog's `detailed`
# body (hook-secret-handling discipline: hook stdout is model input and is
# prompt-injection-reachable).

MARKER_BEGIN='<!-- acing-hyperspace:begin -->'
MARKER_END='<!-- acing-hyperspace:end -->'

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-.}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
PRIMER_SRC="$PLUGIN_ROOT/skills/acing-hyperspace/SKILL.md"

main() {
    INPUT="$(cat 2>/dev/null)"
    SOURCE="$(printf '%s' "$INPUT" | tr '\n' ' ' | sed -n 's/.*"source"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    [ -z "$SOURCE" ] && SOURCE="unknown"

    printf '=== Hyperspace Engine — session preload (source=%s) ===\n\n' "$SOURCE"

    printf '%s\n' "$MARKER_BEGIN"
    if [ -r "$PRIMER_SRC" ]; then
        awk '
            NR == 1 && $0 == "---" { infrontmatter = 1; next }
            infrontmatter && $0 == "---" { infrontmatter = 0; skipblank = 1; next }
            infrontmatter { next }
            skipblank { skipblank = 0; if ($0 == "") next }
            { print }
        ' "$PRIMER_SRC"
    else
        printf '⚠️ acing-hyperspace primer MISSING at %s — the loop router is inert this session.\n' "$PRIMER_SRC"
    fi
    printf '%s\n\n' "$MARKER_END"

    PY=""
    if [ -x "$PROJECT_DIR/.hyperspace/env/bin/python" ]; then
        PY="$PROJECT_DIR/.hyperspace/env/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        PY="$(command -v python3)"
    fi

    if [ -z "$PY" ]; then
        printf '⚠️ python3 not found on PATH — skipping the active-run and worklog blocks (bin/loop_state.py and the local task graph both need it).\n'
        return 0
    fi

    "$PY" - "$PROJECT_DIR" "$PLUGIN_ROOT" "$SOURCE" <<'PYEOF'
# Renders the active-loop-run block (with the T3.6 startup/compact budget
# bump folded in) and the recent-worklog block, both against the project the
# session opened in. Every exception is caught locally so one bad run folder,
# one unreadable config, or a database error degrades that one block rather
# than the whole hook — see the module docstring in bin/loop_state.py for the
# verbs this calls (`bump`, `notify`) and hyperspace/store/schema.sql for the
# `worklog` table shape this reads directly (a coupling named in
# docs/reference/tripwires.md).
import json
import re
import sqlite3
import sys
from pathlib import Path

project_dir = Path(sys.argv[1])
plugin_root = Path(sys.argv[2])
source = sys.argv[3]

sys.path.insert(0, str(plugin_root / "bin"))

try:
    import loop_state
    import loop_terminal
    TERMINAL_STATUSES = set(loop_terminal.LEGITIMATE_TERMINAL)
except Exception:
    loop_state = None
    TERMINAL_STATUSES = {"done", "descoped", "killed"}

_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_BUMP_EVENTS = ("startup", "compact")


def _safe_field(value):
    """A field pulled from loop.state.json is model input reaching hook
    stdout — never print it unless it is a short enum-shaped token."""
    if isinstance(value, str) and _SLUG_RE.match(value):
        return value
    return "unknown"


# ---- active loop runs -------------------------------------------------
run_lines = []
runs_dir = project_dir / "hyperspace" / "runs"
if runs_dir.is_dir():
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

        if data.get("status") in TERMINAL_STATUSES:
            continue

        notify_lines = []
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
        run_lines.append(
            "goal=%s · status=%s · node=%s · gates_passed=%d"
            % (
                _safe_field(data.get("goal_slug")),
                _safe_field(data.get("status")),
                _safe_field(data.get("current_node")),
                gates_passed,
            )
        )
        run_lines.extend(notify_lines)

if run_lines:
    print("## Active loop")
    for line in run_lines:
        print(line)
    print("")

# ---- recent worklog -----------------------------------------------------
hyperspace_dir = project_dir / ".hyperspace"
if not hyperspace_dir.is_dir():
    print(
        "No .hyperspace/ found in this project yet — run the "
        "`hyperspace-setup` skill to turn Hyperspace Engine on."
    )
else:
    graph_db = hyperspace_dir / "graph.db"
    if graph_db.is_file():
        # `worklog_owner` (default "hyperspace-engine"): a config.toml key
        # this hook alone reads. hyperspace/config.py's Config dataclass has
        # no field for it and never will need one — an unrecognized key in a
        # flat TOML file is inert to every other reader, and load_config()
        # only ever `.get()`s the four keys it knows. Lets a future
        # integration that owns its own worklog display opt this block off
        # without editing this hook.
        worklog_owner = "hyperspace-engine"
        config_path = hyperspace_dir / "config.toml"
        if config_path.is_file():
            try:
                import tomllib
                with config_path.open("rb") as fh:
                    cfg = tomllib.load(fh)
                raw_owner = cfg.get("worklog_owner")
                if isinstance(raw_owner, str) and raw_owner.strip():
                    worklog_owner = raw_owner.strip()
            except Exception:
                pass

        if worklog_owner == "hyperspace-engine":
            rows = []
            try:
                conn = sqlite3.connect(f"file:{graph_db}?mode=ro", uri=True)
                try:
                    rows = conn.execute(
                        "SELECT created_at, author, summary FROM worklog "
                        "ORDER BY created_at DESC LIMIT 5"
                    ).fetchall()
                finally:
                    conn.close()
            except Exception:
                rows = []

            if rows:
                print("## Recent worklog")
                for created_at, author, summary in rows:
                    date = created_at[:10] if isinstance(created_at, str) else ""
                    author_s = author if isinstance(author, str) else ""
                    # Store already caps summary at 280 chars on write
                    # (hyperspace/tools/reads.py); re-cap defensively so a
                    # row inserted by any other path can never blow the
                    # hook's own output budget.
                    summary_s = summary[:280] if isinstance(summary, str) else ""
                    print("- %s | %s | %s" % (date, author_s, summary_s))
                print("")
PYEOF
    return 0
}

main
exit 0
