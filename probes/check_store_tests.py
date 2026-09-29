#!/usr/bin/env python3
"""T2.1 verdict check: the store's unit tests pass, `hyperspace init` produces
all eleven tables + `meta`, and filings are append-only.

Three sub-checks, all must PASS:
  (a) `.venv/bin/python -m pytest tests/test_store.py -q` (explicit target)
  (b) `hyperspace init` in a fresh temp dir creates `.hyperspace/graph.db` with
      the eleven console tables + `meta`
  (c) a second `add_filing` for the same external_id, different idempotency
      key, leaves the first filing's `candidate_json` unchanged (append-only)

Usage: probes/check_store_tests.py --out <path>
"""
import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from hyperspace.venv_paths import find_venv_python  # noqa: E402

ELEVEN_TABLES = {
    "projects", "modules", "work_items", "work_item_relations", "cycles",
    "cycle_assignments", "initiatives", "initiative_links", "worklog",
    "verifier_runs", "filings",
}


def _trim(text: str, limit: int = 4000) -> str:
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def check_pytest(evidence: dict) -> bool:
    venv_python = ROOT / ".venv" / "bin" / "python"
    python = venv_python if venv_python.exists() else Path(sys.executable)
    proc = subprocess.run(
        [str(python), "-m", "pytest", "tests/test_store.py", "-q"],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8", errors="replace",
    )
    summary_line = ""
    for line in proc.stdout.splitlines()[::-1]:
        if "passed" in line or "failed" in line or "error" in line:
            summary_line = line.strip()
            break
    evidence["pytest"] = {
        "command": f"{python} -m pytest tests/test_store.py -q",
        "exit_code": proc.returncode,
        "summary_line": summary_line,
        "stdout": _trim(proc.stdout),
        "stderr": _trim(proc.stderr),
    }
    return proc.returncode == 0


def check_init_and_tables(evidence: dict) -> bool:
    venv_python = find_venv_python(ROOT / ".venv") or Path(sys.executable)
    hyperspace_bin = shutil.which("hyperspace", path=str(venv_python.parent)) or shutil.which("hyperspace")
    if hyperspace_bin is None or not Path(hyperspace_bin).exists():
        evidence["init_and_tables"] = {"error": "hyperspace console script not found"}
        return False

    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir()
        proc = subprocess.run(
            [str(hyperspace_bin), "init", "--dir", str(project_dir)],
            capture_output=True,
            encoding="utf-8", errors="replace",
        )
        db_path = project_dir / ".hyperspace" / "graph.db"
        tables: list[str] = []
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()]
            conn.close()

        evidence["init_and_tables"] = {
            "command": f"{hyperspace_bin} init --dir {project_dir}",
            "exit_code": proc.returncode,
            "stdout": _trim(proc.stdout),
            "stderr": _trim(proc.stderr),
            "db_exists": db_path.exists(),
            "tables": sorted(tables),
        }
        return (
            proc.returncode == 0
            and db_path.exists()
            and ELEVEN_TABLES <= set(tables)
            and "meta" in tables
        )


def check_filings_append_only(evidence: dict) -> bool:
    sys.path.insert(0, str(ROOT))
    from hyperspace.store import Store

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / ".hyperspace" / "graph.db"
        store = Store.init(db_path)
        try:
            store.upsert_project(code="probe-project", name="Probe")
            store.upsert_work_item(
                project_code="probe-project", external_id="probe-project:wi-1",
                name="Probe item", type="task", state="ready",
            )
            candidate_v1 = {"name": "Probe item", "acceptance_criteria": [{"statement": "v1"}]}
            filing_1 = store.add_filing(
                external_id="probe-project:wi-1", project_code="probe-project",
                idempotency_key="probe-key-1", candidate=candidate_v1,
            )
            before = store.get_filing(filing_1)["candidate_json"]

            candidate_v2 = {"name": "Probe item", "acceptance_criteria": [{"statement": "v2"}]}
            filing_2 = store.add_filing(
                external_id="probe-project:wi-1", project_code="probe-project",
                idempotency_key="probe-key-2", candidate=candidate_v2,
            )
            after = store.get_filing(filing_1)["candidate_json"]

            two_rows = filing_1 != filing_2
            unchanged = before == after == json.dumps(candidate_v1)
            second_recorded = json.loads(store.get_filing(filing_2)["candidate_json"]) == candidate_v2

            evidence["filings_append_only"] = {
                "filing_1": filing_1,
                "filing_2": filing_2,
                "two_distinct_rows": two_rows,
                "first_unchanged": unchanged,
                "second_recorded": second_recorded,
            }
            return two_rows and unchanged and second_recorded
        finally:
            store.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    evidence: dict = {}
    a = check_pytest(evidence)
    b = check_init_and_tables(evidence)
    c = check_filings_append_only(evidence)

    result = "PASS" if (a and b and c) else "FAIL"
    write_verdict(args.out, probe="hsp_sqlite_store", result=result, evidence=evidence)

    print(f"hsp_sqlite_store: {result} (pytest={a} init_and_tables={b} filings_append_only={c})")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
