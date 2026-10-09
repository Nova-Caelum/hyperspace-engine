"""hyperspace/http/runs.py — the runs a project has, read off disk for the console
(`GET /api/projects/<code>/runs`, row HSE-94).

A run is one `<project>/hyperspace/runs/<slug>/loop.state.json`; the SessionStart
hook and Technical Cofounder's briefing both look in exactly that place. The file
is read as plain JSON, not through `bin/loop_state.py`: a state file with only a
status in it still lists, and this module must run from the wheel installed into a
user's `.hyperspace/env`, which carries `hyperspace/` and `ui/dist` but not `bin/`.
"""
from __future__ import annotations

import json
from pathlib import Path

#: `bin/loop_terminal.py::LEGITIMATE_TERMINAL`, copied because `bin/` is not in the
#: installed package. `tests/test_http_console.py::test_terminal_set_is_the_one_loop_state_defines`
#: fails if this and that set (or the schema's `final_route` enum) ever differ.
TERMINAL_STATUSES = frozenset({"done", "descoped", "killed"})


def project_root(db_path: Path) -> Path:
    """The directory `hyperspace init` was run in: the door's database is always
    `<root>/.hyperspace/graph.db` (`hyperspace.cli._prepare_serve`)."""
    return Path(db_path).resolve().parent.parent


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def list_runs(root: Path) -> list[dict]:
    """Every run under `<root>/hyperspace/runs`, ordered by folder name:
    `{goal, status, current_node, run_folder, open}`. `goal` is the state file's
    `goal_slug` (which is also the folder name); `run_folder` is relative to `root`;
    `open` is `status` not in the terminal set. A state file that is not readable
    JSON, or not an object, is skipped."""
    runs: list[dict] = []
    for state_path in sorted((root / "hyperspace" / "runs").glob("*/loop.state.json")):
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        status = _text(data.get("status"))
        runs.append({
            "goal": _text(data.get("goal_slug")) or state_path.parent.name,
            "status": status,
            "current_node": _text(data.get("current_node")),
            "run_folder": state_path.parent.relative_to(root).as_posix(),
            "open": status not in TERMINAL_STATUSES,
        })
    return runs
