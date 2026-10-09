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
# Runs under `sh -c` on macOS and Linux and under Git Bash on Windows (Claude
# Code's shell for shell-form hooks there; see docs/reference/tripwires.md).
# POSIX sh only, and no dependency beyond what the plugin already requires.
# This file does the three things that must work with NO Python at all — read
# `source`, print the primer, say what setup state the project is in — then
# finds an interpreter and hands the Python-shaped work (active runs, budget
# counters, recent worklog) to hooks/session_start.py.
#
# Fail-open by construction: no `set -e`, and this script always exits 0 —
# SessionStart hooks are non-blocking in Claude Code, so a non-zero exit here
# would only hide a real failure from the transcript, never actually stop the
# session. Hook stdout is model input (hook-secret-handling discipline): this
# script prints only the primer, fixed text, and paths it built itself.

MARKER_BEGIN='<!-- acing-hyperspace:begin -->'
MARKER_END='<!-- acing-hyperspace:end -->'

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-.}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
PRIMER_SRC="$PLUGIN_ROOT/skills/acing-hyperspace/SKILL.md"

# True when the command in "$@" runs Python >= 3.11. Every candidate is
# EXECUTED before it is trusted: `command -v python3` on Windows can find the
# Microsoft Store placeholder, which prints an install prompt and exits
# non-zero instead of running.
python_ok() {
    "$@" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

# Sets PY (and PY_ARG, for `py -3`) to the first interpreter python_ok
# accepts, in this order: python3, python, the Windows `py` launcher, then the
# versioned names python3.13, python3.12, python3.11 — on PATH, then by explicit
# path in $HOME/.local/bin (where uv links them, and which a hook's PATH may
# lack). A Mac's own `python3` is 3.9 and fails python_ok, so without the
# versioned names the hook would find nothing there.
#
# The project's own `.hyperspace/env` is deliberately NOT a candidate. This hook
# runs on every SessionStart in every folder Claude Code opens, and a folder can
# ship a file at `.hyperspace/env/bin/python` — trying it would run whatever
# that file is. hooks/session_start.py is stdlib-only (plus this plugin's own
# bin/), so the computer's own Python is all it needs.
find_python() {
    PY=""
    PY_ARG=""
    for name in python3 python; do
        candidate="$(command -v "$name" 2>/dev/null)"
        if [ -n "$candidate" ] && python_ok "$candidate"; then
            PY="$candidate"
            return 0
        fi
    done
    candidate="$(command -v py 2>/dev/null)"
    if [ -n "$candidate" ] && python_ok "$candidate" -3; then
        PY="$candidate"
        PY_ARG="-3"
        return 0
    fi
    versioned="python3.13 python3.12 python3.11"
    for name in $versioned; do
        candidate="$(command -v "$name" 2>/dev/null)"
        if [ -n "$candidate" ] && python_ok "$candidate"; then
            PY="$candidate"
            return 0
        fi
    done
    if [ -n "${HOME:-}" ]; then
        for name in $versioned; do
            candidate="$HOME/.local/bin/$name"
            if { [ -f "$candidate" ] || [ -f "$candidate.exe" ]; } && python_ok "$candidate"; then
                PY="$candidate"
                return 0
            fi
        done
    fi
    return 1
}

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

    ENV_PYTHON="$PROJECT_DIR/.hyperspace/env/bin/python"
    if [ ! -d "$PROJECT_DIR/.hyperspace" ]; then
        printf 'No .hyperspace/ found in this project yet — run the `hyperspace-setup` skill to turn Hyperspace Engine on.\n\n'
    elif [ ! -f "$ENV_PYTHON" ] && [ ! -f "$ENV_PYTHON.exe" ]; then
        printf '⚠️ The hyperspace MCP server cannot start: %s is missing (the plugin runs .hyperspace/env/bin/python). Run the `hyperspace-setup` skill, then restart the session.\n\n' \
            "$ENV_PYTHON"
    fi

    if ! find_python; then
        printf '⚠️ No Python 3.11+ found (tried python3, python, py -3, python3.13/.12/.11) — skipping the active-run and worklog blocks.\n'
        return 0
    fi

    "$PY" $PY_ARG "$PLUGIN_ROOT/hooks/session_start.py" "$PROJECT_DIR" "$PLUGIN_ROOT" "$SOURCE"
    return 0
}

main
exit 0
