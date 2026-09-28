#!/usr/bin/env python3
"""T3.1 verdict check: the verification-graph tests pass, and the graph is a
pydantic graph whose BaseNode steps are exactly Vet, CriteriaQuality, Landing,
EvidenceJudge and Commit.

PASS only if `pytest tests/test_verify.py` exits 0 AND the node list equals the
five. Evidence carries the pytest summary line, the node names, and the outcome
each of the done / unverifiable / already-true-at-filing tests observed.

Usage: probes/check_verify_tests.py --out <path>
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NODES = ["Commit", "CriteriaQuality", "EvidenceJudge", "Landing", "Vet"]
# test -> the outcome it asserts; read back from pytest's per-test result.
OUTCOME_TESTS = {
    "test_done_path_none_judge": "done",
    "test_unattested_manual_is_unverifiable": "unverifiable",
    "test_file_present_before_filing_is_not_done": "unverifiable",
    "test_committed_before_filing_is_refused": "refused",
}


def _trim(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def check_pytest(evidence: dict) -> bool:
    venv_python = ROOT / ".venv" / "bin" / "python"
    python = venv_python if venv_python.exists() else Path(sys.executable)
    proc = subprocess.run(
        [str(python), "-m", "pytest", "tests/test_verify.py", "-q", "-rA"],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
    )
    lines = proc.stdout.splitlines()
    summary_line = next((l.strip() for l in reversed(lines)
                         if " passed" in l or " failed" in l or " error" in l), "")
    observed = {}
    for test, outcome in OUTCOME_TESTS.items():
        status = next((l.split()[0] for l in lines if l.startswith(("PASSED", "FAILED", "ERROR")) and l.endswith(test)), None)
        observed[test] = outcome if status == "PASSED" else f"{status or 'NOT RUN'} (expected {outcome})"
    evidence["pytest"] = {
        "command": f"{python} -m pytest tests/test_verify.py -q -rA",
        "exit_code": proc.returncode,
        "summary_line": summary_line,
        "stderr": _trim(proc.stderr),
    }
    evidence["outcomes_observed"] = observed
    return proc.returncode == 0 and all(not v.startswith(("FAILED", "ERROR", "NOT RUN")) for v in observed.values())


def check_nodes(evidence: dict) -> bool:
    sys.path.insert(0, str(ROOT))
    import pydantic_graph
    from pydantic_graph.step import NodeStep

    from hyperspace.verify.graph import verification_graph

    names = sorted(n.node_type.__name__ for n in verification_graph.nodes.values() if isinstance(n, NodeStep))
    evidence["graph"] = {
        "is_pydantic_graph": isinstance(verification_graph, pydantic_graph.Graph),
        "name": verification_graph.name,
        "node_names": names,
        "api": "sorted(n.node_type.__name__ for n in verification_graph.nodes.values() if isinstance(n, NodeStep))",
    }
    return isinstance(verification_graph, pydantic_graph.Graph) and names == EXPECTED_NODES


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    evidence: dict = {}
    a = check_pytest(evidence)
    b = check_nodes(evidence)
    result = "PASS" if (a and b) else "FAIL"
    write_verdict(args.out, probe="hsp_verification_graph", result=result, evidence=evidence)
    print(f"hsp_verification_graph: {result} (pytest={a} nodes={b})")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
