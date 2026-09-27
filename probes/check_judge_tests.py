#!/usr/bin/env python3
"""T3.2 verdict check: the judge-runner tests pass, and all five configured
judge names resolve through `get_judge` to a runner instance (or, for a keyed
runner whose key is absent in this environment, a `JudgeUnavailable` naming
that same runner — still a resolved mapping, just an unavailable one).

PASS only if `pytest tests/test_judge.py` exits 0 AND all five names resolve.
Evidence carries the pytest summary line and the five resolved names.
`real_calls` is always `false` — this probe never makes a network or CLI call.

Usage: probes/check_judge_tests.py --out <path>
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _trim(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def check_pytest(evidence: dict) -> bool:
    venv_python = ROOT / ".venv" / "bin" / "python"
    python = venv_python if venv_python.exists() else Path(sys.executable)
    proc = subprocess.run(
        [str(python), "-m", "pytest", "tests/test_judge.py", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    lines = proc.stdout.splitlines()
    summary = next((l.strip() for l in reversed(lines)
                    if " passed" in l or " failed" in l or " error" in l), "")
    evidence["pytest"] = {
        "command": f"{python} -m pytest tests/test_judge.py -q",
        "exit_code": proc.returncode,
        "summary": summary,
        "stderr": _trim(proc.stderr),
    }
    return proc.returncode == 0


def check_resolves(evidence: dict) -> bool:
    sys.path.insert(0, str(ROOT))
    from hyperspace.config import JUDGES, Config
    from hyperspace.judge import JudgeUnavailable, get_judge

    resolved: list[str] = []
    detail: dict[str, str] = {}
    for judge in JUDGES:
        try:
            instance = get_judge(Config(judge=judge))
            resolved.append(instance.name)
            detail[judge] = "constructed"
        except JudgeUnavailable as exc:
            # A keyed runner with no key in THIS environment still resolved
            # correctly through `get_judge`'s mapping — it just reports the
            # one unavailability its own interface defines, naming itself.
            resolved.append(exc.runner)
            detail[judge] = f"unavailable: {exc.reason}"
    evidence["get_judge"] = {
        "expected_names": list(JUDGES),
        "resolved_names": resolved,
        "detail": detail,
    }
    return resolved == list(JUDGES)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    evidence: dict = {"real_calls": False}
    pytest_ok = check_pytest(evidence)
    resolves_ok = check_resolves(evidence)
    result = "PASS" if (pytest_ok and resolves_ok) else "FAIL"
    write_verdict(args.out, probe="hsp_judge_tests", result=result, evidence=evidence)
    print(f"hsp_judge_tests: {result} (pytest={pytest_ok} resolves={resolves_ok})")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
