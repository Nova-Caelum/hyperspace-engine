#!/usr/bin/env python3
"""T2.2 verdict check: the graph-tools unit tests pass, and a scripted smoke
calls each of the seventeen graph tools against a temporary store and gets a
typed result with no `error` key back, then exercises the S2 sequence (file
a work item, update its criteria under the ORIGINAL idempotency_key with
`update_acceptance_criteria: true`, and assert the new filing's key differs
from the original).

Usage: probes/check_tools_tests.py --out <path>
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# The sixteen named by the row's Plan acceptance text, plus the seventeenth
# (`list_initiatives`) the brief calls out separately (gear3's principles
# snapshot). All seventeen are exercised; PASS requires every one of them.
SIXTEEN_TOOL_NAMES = [
    "upsert_work_item", "get_graph_run", "list_work_items", "append_worklog",
    "link_work_items", "upsert_module", "get_recent_activity",
    "list_initiative_links", "list_agents", "get_work_item", "get_project",
    "list_projects", "upsert_cycle", "assign_cycle_work_items",
    "upsert_initiative", "link_initiative_objects",
]
SEVENTEENTH_TOOL_NAME = "list_initiatives"
ALL_TOOL_NAMES = SIXTEEN_TOOL_NAMES + [SEVENTEENTH_TOOL_NAME]


def _trim(text: str, limit: int = 4000) -> str:
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def check_pytest(evidence: dict) -> bool:
    venv_python = ROOT / ".venv" / "bin" / "python"
    python = venv_python if venv_python.exists() else Path(sys.executable)
    proc = subprocess.run(
        [str(python), "-m", "pytest", "tests/test_tools.py", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    summary_line = ""
    for line in proc.stdout.splitlines()[::-1]:
        if "passed" in line or "failed" in line or "error" in line:
            summary_line = line.strip()
            break
    evidence["pytest"] = {
        "command": f"{python} -m pytest tests/test_tools.py -q",
        "exit_code": proc.returncode,
        "summary_line": summary_line,
        "stdout": _trim(proc.stdout),
        "stderr": _trim(proc.stderr),
    }
    return proc.returncode == 0


def _candidate(external_id: str, idempotency_key: str, statement: str = "Exits 0 when run.", **overrides) -> dict:
    payload = {
        "project": "probe-project",
        "external_id": external_id,
        "name": "Probe item",
        "type": "task",
        "state": None,
        "parent_work_item": None,
        "assignee_agent": None,
        "team": None,
        "idempotency_key": idempotency_key,
        "specification": {
            "problem": "The probe needs a filed work item to exercise every graph tool end to end.",
            "why_it_matters": "Without a real filing the smoke check cannot prove the table dispatches.",
            "context_pointer": "probes/check_tools_tests.py",
        },
        "source_references": [{"uri": "probes/check_tools_tests.py"}],
        "effort_level": "quick",
        "module": None,
        "acceptance_criteria": [
            {"statement": statement, "verification": {"kind": "command_check", "check_id": "tests"}},
        ],
        "proposer_identity": "probe",
        "proposer_surface": "cli-mac",
        "uncertainty_notes": [],
    }
    payload.update(overrides)
    return payload


def check_tools_smoke(evidence: dict) -> bool:
    sys.path.insert(0, str(ROOT))
    from hyperspace.store import Store
    from hyperspace.tools import call_tool

    all_ok = True
    result_keys: dict = {}

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / ".hyperspace" / "graph.db"
        store = Store.init(db_path)

        def run(name: str, args: dict):
            nonlocal all_ok
            result = call_tool(store, name, args)
            if isinstance(result, dict) and "error" in result:
                all_ok = False
                result_keys[name] = f"error: {result['error']}"
            elif isinstance(result, list):
                result_keys[name] = "list"
            elif isinstance(result, dict):
                result_keys[name] = sorted(result.keys())
            else:
                result_keys[name] = str(type(result))
            return result

        try:
            run("upsert_project", {"code": "probe-project", "name": "Probe"})
            filed = run("upsert_work_item", _candidate("probe-project:wi-1", "wi-1-create"))
            run("upsert_work_item", _candidate("probe-project:wi-2", "wi-2-create"))

            ref = None
            if isinstance(filed, dict) and "row" in filed:
                ref = filed["row"]["acceptance_criteria_ref"]
            run("get_graph_run", {"run_id": ref or "missing"})

            run("get_work_item", {"external_id": "probe-project:wi-1", "project": "probe-project"})
            run("list_work_items", {"project": "probe-project"})
            run("link_work_items", {
                "project": "probe-project", "item": "probe-project:wi-1",
                "related_item": "probe-project:wi-2", "relation_type": "blocks",
            })
            run("upsert_module", {
                "project": "probe-project", "external_id": "probe-project:mod-1",
                "name": "Probe module",
                "acceptance_criteria": "Every child work item in this module is done.",
            })
            run("append_worklog", {"author": "probe", "project": "probe-project", "summary": "Probe smoke."})
            run("get_recent_activity", {"limit": 5})
            run("upsert_initiative", {"external_id": "probe-init-1", "title": "Probe initiative"})
            run("link_initiative_objects", {"initiative": "probe-init-1", "work_items": ["probe-project:wi-1"]})
            run("list_initiative_links", {"initiative": "probe-init-1"})
            run("list_agents", {})
            run("get_project", {"code": "probe-project"})
            run("list_projects", {})
            run("upsert_cycle", {"project": "probe-project", "external_id": "probe-project:cycle-1", "name": "Probe cycle"})
            run("assign_cycle_work_items", {
                "project": "probe-project", "cycle": "probe-project:cycle-1",
                "work_items": ["probe-project:wi-1"],
            })
            run(SEVENTEENTH_TOOL_NAME, {})

            missing = [n for n in ALL_TOOL_NAMES if n not in result_keys]
            if missing:
                all_ok = False
                result_keys["_missing"] = missing

            # S2 sequence: same external_id, ORIGINAL idempotency_key, changed
            # criteria, update_acceptance_criteria=True -> fresh key minted.
            second = run("upsert_work_item", _candidate(
                "probe-project:wi-1", "wi-1-create",
                statement="Exits 0 AND the smoke check reads its own output.",
                update_acceptance_criteria=True,
            ))
            s2_keys = {"original_idempotency_key": "wi-1-create", "fresh_filing_idempotency_key": None}
            if isinstance(second, dict) and "filing_id" in second:
                new_filing = store.get_filing(second["filing_id"])
                fresh_key = new_filing["idempotency_key"] if new_filing else None
                s2_keys["fresh_filing_idempotency_key"] = fresh_key
                if fresh_key is None or fresh_key == "wi-1-create":
                    all_ok = False
            else:
                all_ok = False
            evidence["s2_keys"] = s2_keys
        finally:
            store.close()

    evidence["tool_results"] = result_keys
    return all_ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    evidence: dict = {}
    a = check_pytest(evidence)
    b = check_tools_smoke(evidence)

    result = "PASS" if (a and b) else "FAIL"
    write_verdict(args.out, probe="hsp_graph_tools", result=result, evidence=evidence)

    print(f"hsp_graph_tools: {result} (pytest={a} smoke={b})")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
