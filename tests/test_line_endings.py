"""Shell scripts are checked out with Unix line endings on every system.

Git for Windows defaults to `core.autocrlf=true`, which rewrites LF to CRLF at
checkout; a CRLF after `#!/bin/sh` then fails under Git Bash. `.gitattributes`
pins `eol=lf` so a checkout never converts, whatever the machine's git config.
`git ls-files --eol` reports all three views: `i/` the index, `w/` the working
tree, `attr/` the attributes git applies.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SUFFIXES = (".sh", ".command")
EOL_FIELDS = re.compile(r"^i/(\S+)\s+w/(\S+)\s+attr/(.*?)\s*$")


def _tracked_files():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout, so there are no attributes to read")
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--eol", "-z"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    rows = []
    for entry in filter(None, out.split("\0")):
        info, _, path = entry.partition("\t")
        fields = EOL_FIELDS.match(info)
        assert fields, f"unrecognised `git ls-files --eol` row: {entry!r}"
        rows.append((path, *fields.groups()))
    return rows


def test_every_shell_script_is_lf_in_index_working_tree_and_attributes():
    scripts = [row for row in _tracked_files() if row[0].endswith(SCRIPT_SUFFIXES)]
    assert scripts, "expected tracked shell scripts (hooks/session-start.sh at least)"
    wrong = [
        f"{path}: i/{index} w/{work} attr/{attr}"
        for path, index, work, attr in scripts
        if (index, work, attr) != ("lf", "lf", "text=auto eol=lf")
    ]
    assert not wrong, "scripts not pinned to LF by .gitattributes:\n" + "\n".join(wrong)


def test_binary_files_are_declared_binary():
    undeclared = [
        f"{path}: attr/{attr or '(none)'}"
        for path, index, _work, attr in _tracked_files()
        if index == "-text" and not attr.startswith("-text")
    ]
    assert not undeclared, "binary files without a `binary` attribute:\n" + "\n".join(undeclared)
