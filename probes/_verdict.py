"""Shared verdict-writing helper every check script in this repo imports.

Stdlib-only by design — probes must run without the package's own runtime
dependencies installed.
"""
import json
from datetime import datetime, timezone
from pathlib import Path


def write_verdict(out_path, probe: str, result: str, evidence: dict) -> None:
    """Write a probe verdict as JSON to `out_path`, creating parent dirs.

    `result` is "PASS" or "FAIL". The written object is
    `{"probe", "result", "evidence", "ran_at"}` with `ran_at` a UTC
    ISO-8601 timestamp.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "probe": probe,
        "result": result,
        "evidence": evidence,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
