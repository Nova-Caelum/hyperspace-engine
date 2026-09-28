#!/usr/bin/env python3
"""probes/probe_installer.py — T9: a fresh-directory, non-interactive dry run
of the hyperspace-setup skill's steps, no key and no `claude`/`codex` on PATH.

Composes `probes/check_installer.py` entirely — its own `main()` already
writes a verdict in exactly this shape at the path it is given — never
re-implemented.

Usage: imported by probes/run.py; PROBE = "installer"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROBE = "installer"


def run(out_dir, opts) -> bool:
    venv_python = ROOT / ".venv" / "bin" / "python"
    python = venv_python if venv_python.exists() else Path(sys.executable)
    dest = Path(out_dir) / f"{PROBE}.json"

    proc = subprocess.run(
        [str(python), str(ROOT / "probes" / "check_installer.py"), "--out", str(dest)],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
    )

    if dest.is_file():
        # check_installer.py writes its own verdict in the shared shape;
        # its exit code already mirrors that verdict's result.
        return proc.returncode == 0

    # A genuinely broken environment can make check_installer.py exit before
    # it ever wrote anything — record the raw command output rather than
    # silently returning a false PASS.
    write_verdict(
        dest, probe=PROBE, result="FAIL",
        evidence={
            "command": f"{python} probes/check_installer.py --out {dest}",
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        },
    )
    return False
