#!/usr/bin/env python3
"""probes/probe_known_defects.py — T13: the product's own regression suite
proves it does not inherit S1/S2 and confirms S3 is out of its path.

Runs `tests/test_known_defects.py` under the repo's own venv.

Usage: imported by probes/run.py; PROBE = "known_defects"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROBE = "known_defects"


def run(out_dir, opts) -> bool:
    venv_python = ROOT / ".venv" / "bin" / "python"
    python = venv_python if venv_python.exists() else Path(sys.executable)
    proc = subprocess.run(
        [str(python), "-m", "pytest", "tests/test_known_defects.py", "-q"],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    ok = proc.returncode == 0
    evidence = {
        "command": f"{python} -m pytest tests/test_known_defects.py -q",
        "exit_code": proc.returncode,
        "summary": lines[-1] if lines else "",
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-2000:],
    }
    write_verdict(Path(out_dir) / f"{PROBE}.json", probe=PROBE, result="PASS" if ok else "FAIL", evidence=evidence)
    return ok
