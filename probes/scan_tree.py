#!/usr/bin/env python3
"""The one tree scanner every scan probe in this repo reuses.

`scan()` walks the named directories under a root and reports every line that
contains one of the given terms. It is a function first and a script second:
the port check, and later the `no_nova_infra`, `no_vault_refs` and
`gear_names` probes, import `scan` rather than each growing its own walker.

Terms are matched as plain substrings (regex-escaped), case-insensitively by
default. Stdlib only, so it runs before the package's dependencies exist.

CLI:
    scan_tree.py --root . --dirs bin skills hyperspace --terms A B C [--ignore-case]
prints one `path:line: [term] text` line per finding and exits 1 if there is
any, 0 if the tree is clean.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: Directory names never descended into.
SKIP_DIRS = frozenset({"__pycache__", ".venv", ".git"})
#: File-name globs never read.
DEFAULT_EXCLUDE_GLOBS: tuple[str, ...] = ("*.pyc",)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    term: str
    text: str


def _iter_files(base: Path, exclude_globs: tuple[str, ...]):
    if base.is_file():
        yield base
        return
    if not base.is_dir():
        return
    for entry in sorted(base.iterdir()):
        if entry.is_dir():
            if entry.name in SKIP_DIRS:
                continue
            yield from _iter_files(entry, exclude_globs)
        elif entry.is_file() and not any(fnmatch.fnmatch(entry.name, g) for g in exclude_globs):
            yield entry


def scan(
    root: Path,
    dirs: list[str],
    terms: list[str],
    *,
    case_insensitive: bool = True,
    exclude_globs: tuple[str, ...] = DEFAULT_EXCLUDE_GLOBS,
) -> list[Finding]:
    """Every line under `root/<dir>` for each `dir` that contains a term.

    Paths in the findings are relative to `root`. A line holding two terms is
    reported once per term. Undecodable files are skipped — the scanned trees
    hold text, and a binary file cannot carry a readable reference."""
    root = Path(root)
    flags = re.IGNORECASE if case_insensitive else 0
    patterns = [(term, re.compile(re.escape(term), flags)) for term in terms]
    findings: list[Finding] = []
    for name in dirs:
        for path in _iter_files(root / name, tuple(exclude_globs)):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                for term, pattern in patterns:
                    if pattern.search(line):
                        findings.append(Finding(path.relative_to(root), lineno, term, line.strip()))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan directories for forbidden terms.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--dirs", nargs="+", required=True)
    parser.add_argument("--terms", nargs="+", required=True)
    parser.add_argument("--ignore-case", action="store_true", dest="ignore_case")
    args = parser.parse_args(argv)

    findings = scan(Path(args.root), args.dirs, args.terms, case_insensitive=args.ignore_case)
    for f in findings:
        print(f"{f.path}:{f.line}: [{f.term}] {f.text}")
    print(f"{len(findings)} finding(s)", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
