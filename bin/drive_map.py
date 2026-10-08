#!/usr/bin/env python3
"""Run-folder schema + drive map for hyperspace runs.

The author, 2026-09-20: by the Build node the run folder "was such a hot mess. I
literally couldn't find anything." Two mechanisms, one file:

* **The schema** — `ROOT_FILES` and `FOLDERS` below are the ONLY list of what
  belongs where in a run folder. The narrative companion
  (`skills/gear2-understand/references/run-folder-schema.md`) covers
  judgment calls only and points at the map's own printed table for the list.
* **The drive map** — `<run-dir>/DRIVE_MAP.md`, GENERATED from the disk, never
  hand-written. `loop_state.py` rewrites it when a run opens (`init`), at every node
  entry (`set-node`) and at every passing gate (`gate-pass`), so "the map matches the drive" holds
  by construction at both ends of every node. Text after the dash on a map
  line is a human/agent description and survives regeneration.

Schema conformance is REPORT-ONLY in v1: anything outside the schema is listed
under "Outside the schema" in the map and echoed to stderr, but nothing is
refused — runs opened before this file existed have untidy roots and must not
be blocked by it.

A second mode maps a whole project rather than one run: `tree <root> --out <file>`
walks <root> under the settings in `<root>/.drivemap.toml` (`exclude`, `cutoff`,
`max_depth`, `budget`) and writes a map an agent reads before it creates a file.
It follows the same rule: text after the dash on a line is yours and survives
regeneration. Details at the `tree mode` section below.

CLI:  drive_map.py write <run-dir>   create missing schema folders, (re)write the map
      drive_map.py check <run-dir>   exit 0 if the map matches the disk, 1 if not
      drive_map.py tree <root> --out <file> [--config <toml>]
                                     map a whole project, honouring .drivemap.toml
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MAP_FILENAME = "DRIVE_MAP.md"

# ---- the schema (single source) -------------------------------------------
# name -> default description. Files the engine itself emits at the run root.
ROOT_FILES: dict[str, str] = {
    "loop.state.json": "Engine state: current node, gates passed, frozen hashes. Never hand-edit.",
    "original_input.md": "The user's ask, verbatim. The run's anchor.",
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

# Shown first in the map when present — the files the user goes looking for.
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
_COUNT_NOTE = re.compile(r"^\(\d+\+? files?, not listed\)\s*")


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
def _existing_descriptions(map_path: Path, heading: str = _FULL_MAP_HEADING) -> dict[str, str]:
    if not map_path.is_file():
        return {}
    found: dict[str, str] = {}
    in_full = False
    for line in map_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_full = line.strip() == heading
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
        "> Generated by the plugin's `bin/drive_map.py` — rewritten at every node entry and "
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


# ---- tree mode: a whole project ------------------------------------------------
# `drive_map.py tree <root> --out <file>` maps a project folder so an agent can
# see where things already live before it creates a file. Settings come from
# `<root>/.drivemap.toml` (optional); every key has a default.
#
#   exclude    globs never listed, never counted
#   cutoff     globs listed as ONE line with a file count, never descended
#   max_depth  levels below <root> that are listed (default 3); a folder at the
#              limit is a cutoff line
#   budget     lines the whole map may take (default 400); over it, the deepest
#              levels collapse to cutoff lines first and the top of the map says so
#
# Globs: a pattern with no "/" matches a file or folder NAME at any depth
# ("*.log", "dist"); one with a "/" matches the path from <root> ("docs/draft-*",
# "runs/*"), where "**" crosses folders ("**/_old"). The tree is walked once;
# excluded folders are never entered, and a cutoff folder is only counted, up to
# COUNT_CAP files, so a huge one costs the same as a small one. The totals in the
# header count what the walk saw (a cutoff folder is one folder plus its count),
# not the lines shown.

CONFIG_FILENAME = ".drivemap.toml"
TREE_HEADING = "## Tree"
DEFAULT_EXCLUDE: tuple[str, ...] = (".*", "dist", "build")
DEFAULT_MAX_DEPTH = 3
DEFAULT_BUDGET = 400
MIN_BUDGET = 12
COUNT_CAP = 5000
_CONFIG_KEYS = ("exclude", "cutoff", "max_depth", "budget")


@dataclass(frozen=True)
class TreeConfig:
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE
    cutoff: tuple[str, ...] = ()
    max_depth: int = DEFAULT_MAX_DEPTH
    budget: int = DEFAULT_BUDGET


@dataclass
class TreeResult:
    text: str
    folders: int
    files: int
    lines: int
    level: int  # deepest level shown; below the configured max_depth when the map was over budget
    path: Path | None = None  # set once written


def load_tree_config(root: Path | str, config_path: Path | str | None = None) -> TreeConfig:
    """Settings from `config_path` (default `<root>/.drivemap.toml`). Absent file: defaults.
    Raises ValueError naming the file and the key when a value is unusable."""
    path = Path(config_path) if config_path else Path(root) / CONFIG_FILENAME
    if not path.is_file():
        return TreeConfig()
    import tomllib  # Python 3.11+; imported here so run-folder mode never needs it

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"{path.name} cannot be read: {exc}") from exc
    unknown = sorted(set(data) - set(_CONFIG_KEYS))
    if unknown:
        print(f"drive map: {path.name} has keys it does not use: {', '.join(unknown)}", file=sys.stderr)

    def globs(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
        value = data.get(key, default)
        if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{path.name}: `{key}` must be a list of strings")
        return tuple(value)

    def whole(key: str, default: int, floor: int) -> int:
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < floor:
            raise ValueError(f"{path.name}: `{key}` must be a whole number, {floor} or more")
        return value

    return TreeConfig(
        exclude=globs("exclude", DEFAULT_EXCLUDE),
        cutoff=globs("cutoff", ()),
        max_depth=whole("max_depth", DEFAULT_MAX_DEPTH, 1),
        budget=whole("budget", DEFAULT_BUDGET, MIN_BUDGET),
    )


class _Globs:
    """A list of path globs, matched against a name (no "/" in the pattern) or the path from the root."""

    def __init__(self, patterns: tuple[str, ...]):
        self._by_name: list[re.Pattern[str]] = []
        self._by_path: list[re.Pattern[str]] = []
        for pattern in patterns:
            body = pattern.replace("\\", "/")
            anchored = "/" in body.rstrip("/")
            body = body.strip("/")
            if body:
                (self._by_path if anchored else self._by_name).append(re.compile(self._regex(body)))

    @staticmethod
    def _regex(body: str) -> str:
        out, i = [], 0
        while i < len(body):
            if body.startswith("**/", i):
                out.append("(?:.*/)?")
                i += 3
            elif body.startswith("**", i):
                out.append(".*")
                i += 2
            elif body[i] == "*":
                out.append("[^/]*")
                i += 1
            elif body[i] == "?":
                out.append("[^/]")
                i += 1
            else:
                out.append(re.escape(body[i]))
                i += 1
        return "".join(out)

    def match(self, name: str, rel: str) -> bool:
        return any(r.fullmatch(name) for r in self._by_name) or any(r.fullmatch(rel) for r in self._by_path)


@dataclass
class _Dir:
    rel: str  # posix path from the root, "" for the root itself
    depth: int  # 0 for the root
    files: list[str] = field(default_factory=list)
    dirs: list["_Dir"] = field(default_factory=list)
    cut: bool = False  # a cutoff or the depth limit: counted, never listed inside
    count: int = 0  # files inside, for a cut folder
    capped: bool = False  # the count stopped at COUNT_CAP


def _join(rel: str, name: str) -> str:
    return f"{rel}/{name}" if rel else name


def _visible(path: str, rel: str, exclude: _Globs) -> list[tuple[os.DirEntry, str]]:
    """(entry, its path from the root) for what `path` holds that is neither ignored nor excluded."""
    try:
        with os.scandir(path) as it:
            found = [(e, _join(rel, e.name)) for e in it]
    except OSError:
        return []  # unreadable: shown as empty rather than failing the map
    return [(e, child) for e, child in found if e.name not in IGNORED_NAMES and not exclude.match(e.name, child)]


def _count_files(path: str, rel: str, exclude: _Globs) -> tuple[int, bool]:
    """Files under `path`, honouring exclude, stopping at COUNT_CAP."""
    total, stack = 0, [(path, rel)]
    while stack:
        for entry, child in _visible(*stack.pop(), exclude):
            if entry.is_dir(follow_symlinks=False):
                stack.append((entry.path, child))
            else:
                total += 1
                if total >= COUNT_CAP:
                    return COUNT_CAP, True
    return total, False


def _scan(path: str, rel: str, depth: int, cfg: TreeConfig, exclude: _Globs, cutoff: _Globs) -> _Dir:
    node = _Dir(rel, depth)
    for entry, child in sorted(_visible(path, rel, exclude), key=lambda ec: (ec[0].name.casefold(), ec[0].name)):
        if not entry.is_dir(follow_symlinks=False):  # a symlinked folder is a plain entry, never followed
            node.files.append(entry.name)
            continue
        sub = _Dir(child, depth + 1)
        if depth + 1 >= cfg.max_depth or cutoff.match(entry.name, child):
            sub.cut = True
            sub.count, sub.capped = _count_files(entry.path, child, exclude)
        else:
            sub = _scan(entry.path, child, depth + 1, cfg, exclude, cutoff)
        node.dirs.append(sub)
    return node


def _inside(node: _Dir) -> tuple[int, bool]:
    """(files in this folder and everything below it, whether any count was capped)."""
    if node.cut:
        return node.count, node.capped
    total, capped = len(node.files), False
    for sub in node.dirs:
        n, c = _inside(sub)
        total, capped = total + n, capped or c
    return total, capped


def _folders(node: _Dir) -> int:
    return sum(1 + (0 if sub.cut else _folders(sub)) for sub in node.dirs)


def _add_file(root: _Dir, rel: str) -> None:
    """List `rel` (the map's own file) in its folder when that folder is listed and the file is not."""
    *parents, name = rel.split("/")
    node = root
    for i in range(len(parents)):
        wanted = "/".join(parents[: i + 1])
        found = next((d for d in node.dirs if d.rel == wanted and not d.cut), None)
        if found is None:
            return
        node = found
    if name not in node.files:
        node.files = sorted([*node.files, name], key=lambda n: (n.casefold(), n))


def _tree_line(path: str, descriptions: dict[str, str]) -> str:
    desc = descriptions.get(path)
    return f"- `{path}` — {desc}" if desc else f"- `{path}`"


def _count(n: int, noun: str, capped: bool = False) -> str:
    return f"{n}{'+' if capped else ''} {noun}{'' if n == 1 else 's'}"


def _cut_line(node: _Dir, descriptions: dict[str, str]) -> str:
    n, capped = _inside(node)
    path = f"{node.rel}/"
    note = descriptions.get(path)
    return f"- `{path}` — ({_count(n, 'file', capped)}, not listed)" + (f" {note}" if note else "")


def _tree_lines(node: _Dir, limit: int, descriptions: dict[str, str]) -> list[str]:
    out = [_tree_line(_join(node.rel, f), descriptions) for f in node.files]
    for sub in node.dirs:
        if sub.cut or sub.depth >= limit:
            out.append(_cut_line(sub, descriptions))
        else:
            out.append(_tree_line(f"{sub.rel}/", descriptions))
            out += _tree_lines(sub, limit, descriptions)
    return out


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def render_tree(
    root: Path | str,
    cfg: TreeConfig | None = None,
    descriptions: dict[str, str] | None = None,
    own_file: str | None = None,
) -> TreeResult:
    """The map for `root`: its text and numbers. `own_file` is the map's path from
    `root` when it lives inside it, so the map lists itself the first time too."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a folder: {root}")
    cfg = cfg or load_tree_config(root)
    descriptions = descriptions or {}
    exclude = _Globs(cfg.exclude)
    tree = _scan(str(root), "", 0, cfg, exclude, _Globs(cfg.cutoff))
    if own_file and not exclude.match(own_file.rsplit("/", 1)[-1], own_file):
        _add_file(tree, own_file)
    n_files, capped = _inside(tree)
    n_folders = _folders(tree)

    def header(note: list[str]) -> list[str]:
        return [
            f"# Drive map — {root.name}",
            "",
            "> Generated by `drive_map.py tree`, rewritten each time it runs (normally at session start). "
            "Never hand-edit a path. The text after the dash on any line under **Tree** is yours: "
            "write it once and it is kept.",
            f"> Generated {_now()}. **{_count(n_folders, 'folder')}, {_count(n_files, 'file', capped)}** "
            f"under `{root.name}/`.",
            f"> Depth {cfg.max_depth}, budget {cfg.budget} lines. Change those, and what is excluded or "
            f"cut off, in `{CONFIG_FILENAME}`.",
            *note,
            "",
            TREE_HEADING,
            "",
        ]

    level, note = cfg.max_depth, []
    while True:
        body = _tree_lines(tree, level, descriptions) or ["- nothing here yet"]
        if len(header(note)) + len(body) <= cfg.budget or level <= 1:
            break
        level -= 1
        note = [
            f"> **Over budget:** listing every level would pass {cfg.budget} lines, so the map stops at level "
            f"{level}: a folder at that level shows its file count instead of its contents. "
            f"Raise `budget` in `{CONFIG_FILENAME}` to see more."
        ]
    room = cfg.budget - len(header(note))
    if len(body) > room:  # one flat folder, or one huge root: a hard ceiling, said plainly
        hidden = len(body) - (room - 1)
        note = [f"> **Over budget:** {hidden} more lines are not listed. Raise `budget` in `{CONFIG_FILENAME}`."]
        body = [*body[: room - 1], f"- … {hidden} more lines, not listed"]
    lines = [*header(note), *body]
    return TreeResult("\n".join(lines) + "\n", n_folders, n_files, len(lines), level)


def write_tree(root: Path | str, out: Path | str, config_path: Path | str | None = None) -> TreeResult:
    """Walk `root`, write the map to `out`, keep the text people wrote after the dash."""
    root, shown = Path(root).resolve(), Path(out)
    out = shown.resolve()
    cfg = load_tree_config(root, config_path)
    try:
        own = out.relative_to(root).as_posix()
    except ValueError:
        own = None
    out.parent.mkdir(parents=True, exist_ok=True)  # before the walk, so a first map already lists its own folder
    result = render_tree(root, cfg, _existing_descriptions(out, TREE_HEADING), own)
    partial = out.with_name(out.name + ".part")
    try:
        partial.write_text(result.text, encoding="utf-8")
        os.replace(partial, out)  # a reader never sees half a map
    finally:
        partial.unlink(missing_ok=True)
    result.path = shown
    return result


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
    tree = sub.add_parser("tree", help="map a whole project folder")
    tree.add_argument("root")
    tree.add_argument("--out", required=True, help="the map file to write")
    tree.add_argument("--config", help=f"settings file (default: <root>/{CONFIG_FILENAME})")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "tree":
            done = write_tree(args.root, args.out, args.config)
            print(f"wrote {done.path} ({done.folders} folders, {done.files} files, {done.lines} lines)")
            return 0
        if args.cmd == "write":
            report_stray(write(args.run_dir))
            print(f"wrote {Path(args.run_dir) / MAP_FILENAME}")
            return 0
        problems = check(args.run_dir)
    except (OSError, ValueError) as exc:
        print(f"drive map: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"fix: python3 {Path(__file__).resolve()} write {args.run_dir}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 even on a Windows ANSI-code-page pipe (hyperspace/_stdio.py)
        _stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
