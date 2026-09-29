"""T5.2 — `probes/run.py`, the one runner every probe in this suite shares.

Covers: (a) an unknown probe name is refused with exit 2 and nothing is
written — not even the `--out` directory; (b) a valid probe run creates
`--out` and writes a verdict file in the shared shape.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _venv_python() -> Path:
    venv_python = ROOT / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def test_unknown_probe_name_refused_writes_nothing(tmp_path):
    out_dir = tmp_path / "nested" / "probes-out"
    proc = subprocess.run(
        [str(_venv_python()), str(ROOT / "probes" / "run.py"), "--out", str(out_dir), "not-a-real-probe"],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "unknown probe name" in proc.stderr
    assert not out_dir.exists(), "run.py must not create --out before validating probe names"


def test_out_dir_is_created_for_a_valid_probe(tmp_path):
    out_dir = tmp_path / "nested" / "probes-out"
    assert not out_dir.exists()

    proc = subprocess.run(
        [str(_venv_python()), str(ROOT / "probes" / "run.py"), "--out", str(out_dir), "gear_names"],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
    )

    assert out_dir.is_dir()
    verdict_path = out_dir / "gear_names.json"
    assert verdict_path.is_file()
    payload = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert payload["probe"] == "gear_names"
    assert payload["result"] in ("PASS", "FAIL")
    assert set(payload.keys()) == {"probe", "result", "evidence", "ran_at"}
    # run.py's own contract is exit 0 iff every NAMED probe reads PASS; a
    # single probe's own PASS/FAIL is that probe's business, not run.py's.
    assert proc.returncode in (0, 1)
