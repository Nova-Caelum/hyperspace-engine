#!/usr/bin/env python3
"""Run-folder schema + drive map for hyperspace runs.

Daniel, 2026-09-20: by the Build node the run folder "was such a hot mess. I
literally couldn't find anything." Two mechanisms, one file:

* **The schema** — `ROOT_FILES` and `FOLDERS` below are the ONLY list of what
  belongs where in a run folder. The narrative companion
  (`skills_library/gear2-understand/references/run-folder-schema.md`) covers
  judgment calls only and points at the map's own printed table for the list.
* **The drive map** — `<run-dir>/DRIVE_MAP.md`, GENERATED from the disk, never
  hand-written. `loop_state.py` rewrites it at every node entry (`set-node`)
  and every passing gate (`gate-pass`), so "the map matches the drive" holds
  by construction at both ends of every node. Text after the dash on a map
  line is a human/agent description and survives regeneration.

Schema conformance is REPORT-ONLY in v1: anything outside the schema is listed
under "Outside the schema" in the map and echoed to stderr, but nothing is
refused — runs opened before this file existed have untidy roots and must not
be blocked by it.

CLI:  drive_map.py write <run-dir>   create missing schema folders, (re)write the map
      drive_map.py check <run-dir>   exit 0 if the map matches the disk, 1 if not
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

MAP_FILENAME = "DRIVE_MAP.md"

# ---- the schema (single source) -------------------------------------------
# name -> default description. Files the engine itself emits at the run root.
ROOT_FILES: dict[str, str] = {
    "loop.state.json": "Engine state: current node, gates passed, frozen hashes. Never hand-edit.",
    "original_input.md": "Daniel's ask, verbatim. The run's anchor.",
    MAP_FILENAME: "This file. Generated; rewritten at every node entry and every gate.",
    "BUILD_LEDGER.md": "Build node: one line per filed row and its status.",
    "RECONCILIATION.md": "Build gate evidence: every row's disposition.",
    "REVIEW.md": "Manual-review record for the run.",
}

# name -> (what goes in it, created by `write`?). Node folders are created by
# their own gear; the three general folders exist from the first `write`.
FOLDERS: dict[str, tuple[str, bool]] = {
    "01_understand": ("Understand node: `Problem.md`, `tests.json`.", False),
    "02_decide": ("Decide node: `Decision.md`, `mapping.json`, `principles.json`, `Deferred.md`.", False),
    "03_draft": ("Draft node: `PRD.md`, `Plan.md`, `workplan.json`, component list.", False),
    "build": ("Build node: one subfolder per row — `build/<row>/brief.md`, `report.md`.", False),
    "handoffs": ("Every handoff, delegation prompt and session-to-session brief.", True),
    "notes": ("Research, analysis, session notes, anything written to think with.", True),
    "misc": ("Whatever fits nowhere else. Better here than loose at the root.", True),
}

# Shown first in the map when present — the files Daniel goes looking for.
KEY_FILES: tuple[str, ...] = (
    "loop.state.json",
    "original_input.md",
    "01_understand/Problem.md",
    "01_understand/tests.json",
    "02_decide/Decision.md",
    "03_draft/PRD.md",
    "03_draft/Plan.md",
    "BUILD_LEDGER.md",
    "RECONCILIATION.md",
)

DEFAULT_DESCRIPTIONS: dict[str, str] = {
    **ROOT_FILES,
    "01_understand/Problem.md": "The real problem, constraints, assumptions. Frozen at the Understand gate.",
    "01_understand/tests.json": "What finished means. Frozen at the Understand gate.",
    "02_decide/Decision.md": "The chosen design and what was cut. Frozen at the Decide gate.",
    "02_decide/mapping.json": "Which component answers which test.",
    "02_decide/principles.json": "Design principles the decision was held to.",
    "02_decide/Deferred.md": "Everything cut from v1, and why.",
    "03_draft/PRD.md": "The PRD. Frozen at the Draft gate.",
    "03_draft/Plan.md": "The build plan, task by task. Frozen at the Draft gate.",
    "03_draft/workplan.json": "The plan as filed to the Task Graph.",
}

IGNORED_NAMES = frozenset(
    {"__pycache__", "node_modules", ".git", ".venv", "venv", ".pytest_cache", ".DS_Store"}
)
# A nested, non-schema directory holding more files than this is shown as one
# counted line — an archive of 300 upstream files is one fact, not 300 lines.
COLLAPSE_OVER = 40

_MAP_LINE = re.compile(r"^- `(?P<path>[^`]+)`(?: — (?P<desc>.*))?$")
_FULL_MAP_HEADING = "## Full map"
_COUNT_NOTE = re.compile(r"^\(\d+ files, not listed\)\s*")


# ---- walking ---------------------------------------------------------------
def _walk(run_dir: Path) -> dict[str, list[str]]:
    """{relative posix dir ('' = root): sorted file names}, ignored names pruned."""
    tree: dict[str, list[str]] = {}
    for current, dirs, files in os.walk(run_dir):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_NAMES)
        rel = Path(current).relative_to(run_dir).as_posix()
        rel = "" if rel == "." else rel
        tree[rel] = sorted(f for f in files if f not in IGNORED_NAMES)
    return tree


def _subtree_count(tree: dict[str, list[str]], rel: str) -> int:
    prefix = rel + "/"
    return sum(len(f) for d, f in tree.items() if d == rel or d.startswith(prefix))


def _collapsed_dirs(tree: dict[str, list[str]]) -> list[str]:
    """Outermost nested non-schema-top-level dirs whose subtree is over the limit."""
    collapsed: list[str] = []
    for rel in sorted(tree):
        if not rel or "/" not in rel:
            continue  # root and top-level folders are always listed in full
        if any(rel == c or rel.startswith(c + "/") for c in collapsed):
            continue
        if _subtree_count(tree, rel) > COLLAPSE_OVER:
            collapsed.append(rel)
    return collapsed


def outside_schema(tree: dict[str, list[str]]) -> list[str]:
    """Loose root files and top-level folders the schema does not name."""
    out = [f for f in tree.get("", []) if f not in ROOT_FILES]
    tops = sorted({d.split("/", 1)[0] for d in tree if d})
    out += [f"{d}/" for d in tops if d not in FOLDERS]
    return out


# ---- rendering ---------------------------------------------------------------
def _existing_descriptions(map_path: Path) -> dict[str, str]:
    if not map_path.is_file():
        return {}
    found: dict[str, str] = {}
    in_full = False
    for line in map_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_full = line.strip() == _FULL_MAP_HEADING
            continue
        match = _MAP_LINE.match(line) if in_full else None
        desc = _COUNT_NOTE.sub("", match.group("desc") or "").strip() if match else ""
        if desc:
            found[match.group("path")] = desc
    return found


def _line(path: str, descriptions: dict[str, str]) -> str:
    desc = descriptions.get(path) or DEFAULT_DESCRIPTIONS.get(path)
    return f"- `{path}` — {desc}" if desc else f"- `{path}`"


def render(run_dir: Path) -> str:
    run_dir = Path(run_dir).resolve()  # "." has no name; the title needs the real folder name
    tree = _walk(run_dir)
    if MAP_FILENAME not in tree.setdefault("", []):
        tree[""] = sorted([*tree[""], MAP_FILENAME])  # the map lists itself
    descriptions = _existing_descriptions(run_dir / MAP_FILENAME)
    collapsed = _collapsed_dirs(tree)
    total = sum(len(f) for f in tree.values())

    out = [
        f"# Drive map — {run_dir.name}",
        "",
        "> Generated by `_agentOS/system/bin/drive_map.py` — rewritten at every node entry and "
        "every gate. Never hand-edit a path. The text after the dash on any line under "
        "**Full map** is yours: write it once and it is kept.",
        f"> **{total} files.**",
        "",
        "## Key files",
        "",
    ]
    all_paths = {f"{d}/{f}" if d else f for d, files in tree.items() for f in files}
    keys = [k for k in KEY_FILES if k in all_paths]
    out += [_line(k, descriptions) for k in keys] or ["- none yet"]

    out += ["", "## Where things go", "", "| Place | What goes there |", "|---|---|"]
    out.append("| run root | Only: " + ", ".join(f"`{n}`" for n in ROOT_FILES) + " |")
    out += [f"| `{name}/` | {purpose} |" for name, (purpose, _) in FOLDERS.items()]

    stray = outside_schema(tree)
    if stray:
        out += ["", f"## Outside the schema ({len(stray)})", ""]
        out.append("File these into a folder above, or into `misc/`. Reported, not refused.")
        out.append("")
        out += [f"- `{p}`" for p in stray]

    out += ["", _FULL_MAP_HEADING]
    for rel in sorted(tree):
        inside = next((c for c in collapsed if rel == c or rel.startswith(c + "/")), None)
        if inside is not None:
            if rel == inside:
                path = f"{rel}/"
                note = descriptions.get(path)
                count = f"({_subtree_count(tree, rel)} files, not listed)"
                out += ["", f"- `{path}` — {count}" + (f" {note}" if note else "")]
            continue
        files = tree[rel]
        if not files and rel:
            continue
        out += ["", f"### {rel + '/' if rel else '(run root)'}", ""]
        out += [_line(f"{rel}/{f}" if rel else f, descriptions) for f in files]
    return "\n".join(out) + "\n"


# ---- operations -----------------------------------------------------------------
def write(run_dir: Path | str) -> list[str]:
    """Create missing schema folders, rewrite the map. Returns outside-schema paths."""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise NotADirectoryError(f"not a run folder: {run_dir}")
    for name, (_, create) in FOLDERS.items():
        if create:
            (run_dir / name).mkdir(exist_ok=True)
    (run_dir / MAP_FILENAME).write_text(render(run_dir), encoding="utf-8")
    return outside_schema(_walk(run_dir))


def check(run_dir: Path | str) -> list[str]:
    """[] when the map on disk is exactly what the disk would generate now."""
    run_dir = Path(run_dir)
    map_path = run_dir / MAP_FILENAME
    if not map_path.is_file():
        return [f"{MAP_FILENAME} is missing"]
    on_disk = map_path.read_text(encoding="utf-8")
    fresh = render(run_dir)
    if on_disk == fresh:
        return []
    have = {m.group("path") for m in map(_MAP_LINE.match, on_disk.splitlines()) if m}
    want = {m.group("path") for m in map(_MAP_LINE.match, fresh.splitlines()) if m}
    problems = [f"on disk, not in the map: {p}" for p in sorted(want - have)]
    problems += [f"in the map, not on disk: {p}" for p in sorted(have - want)]
    return problems or ["the map's text differs from a fresh generation"]


def report_stray(stray: list[str]) -> None:
    if stray:
        print(
            f"drive map: {len(stray)} item(s) outside the run-folder schema — file them "
            f"(listed in {MAP_FILENAME}): " + ", ".join(stray[:8]) + (" …" if len(stray) > 8 else ""),
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("write", "check"):
        sub.add_parser(name).add_argument("run_dir")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "write":
            report_stray(write(args.run_dir))
            print(f"wrote {Path(args.run_dir) / MAP_FILENAME}")
            return 0
        problems = check(args.run_dir)
    except OSError as exc:
        print(f"drive map: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"fix: python3 {Path(__file__).resolve()} write {args.run_dir}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
