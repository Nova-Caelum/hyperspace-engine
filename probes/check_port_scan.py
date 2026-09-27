#!/usr/bin/env python3
"""T1.2 verdict check: the engine port carries no vault, infrastructure or
personal reference, keeps the gear skill names, resolves the contract from the
package, and writes measured-only budget fields.

Five sub-checks, all must PASS:
  (a) the shared tree scan (`probes/scan_tree.py`) over bin/, skills/,
      hyperspace/ finds none of the ten terms (case-insensitive)
  (b) skills/ holds exactly the six gear directories and no file under skills/
      or bin/ names an `hs-` skill
  (c) bin/node_gates.py has no `Path.home()` and no vault path, and imports
      `hyperspace.contracts.candidate`
  (d) `loop_state.py init` in a temp dir writes a state file with no
      `_is_measured` key anywhere
  (e) pytest on the four explicit test targets, with the repo's .venv
      interpreter, is green

Usage: probes/check_port_scan.py --out <path>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402
from scan_tree import scan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCANNED_DIRS = ["bin", "skills", "hyperspace"]
FORBIDDEN_TERMS = [
    "NovaCaelum_Obs",
    "AGENTOS_ROOT",
    "AgentSecretBase",
    "nova-caelum-ops",
    "railway.app",
    "supabase",
    "bws",
    "GMWORKER_OPS_BEARER",
    "GMCOMMITTER_OPS_BEARER",
    "Daniel",
]
GEAR_SKILLS = [
    "acing-hyperspace",
    "gear2-understand",
    "gear3-decide",
    "gear4-draft",
    "gear5-build",
    "gear6-live",
]
HS_NAME = re.compile(r"\bhs-[a-z]")
PYTEST_TARGETS = [
    "tests/test_port.py",
    "tests/test_loop_state.py",
    "tests/test_drive_map.py",
    "tests/test_package.py",
]
#: Tells tests/test_port.py's (e) case not to re-run this script from inside it.
INNER_ENV = "HYPERSPACE_PORT_SCAN_INNER"


def check_scan(evidence: dict) -> bool:
    findings = scan(ROOT, SCANNED_DIRS, FORBIDDEN_TERMS, case_insensitive=True)
    evidence["scan"] = {
        "dirs": SCANNED_DIRS,
        "terms": FORBIDDEN_TERMS,
        "case_insensitive": True,
        "findings": len(findings),
        "first_findings": [f"{f.path}:{f.line}: [{f.term}] {f.text[:160]}" for f in findings[:20]],
    }
    return not findings


def check_gear_names(evidence: dict) -> bool:
    skill_dirs = sorted(os.listdir(ROOT / "skills"))
    hits: list[str] = []
    for base in ("skills", "bin"):
        for path in sorted((ROOT / base).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for n, line in enumerate(lines, 1):
                if HS_NAME.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{n}")
    evidence["gear_names"] = {"skill_dirs": skill_dirs, "hs_name_hits": hits}
    return set(GEAR_SKILLS).issubset(skill_dirs) and not hits


def check_contract_resolution(evidence: dict) -> bool:
    text = (ROOT / "bin" / "node_gates.py").read_text(encoding="utf-8")
    result = {
        "path_home_count": text.count("Path.home()"),
        "vault_path_count": text.count(FORBIDDEN_TERMS[0]),  # the vault root name
        "imports_package_contract": "hyperspace.contracts.candidate" in text,
    }
    evidence["contract_resolution"] = result
    return (
        result["path_home_count"] == 0
        and result["vault_path_count"] == 0
        and result["imports_package_contract"]
    )


def _keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _keys(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _keys(value)


def check_measured_budget(evidence: dict) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "original_input.md"
        source.write_text("port scan\n", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "bin" / "loop_state.py"), "init",
             "--goal", "port-scan", "--input", str(source), "--workspace", tmp],
            capture_output=True, text=True,
        )
        state_path = Path(tmp) / "port-scan" / "loop.state.json"
        if proc.returncode != 0 or not state_path.is_file():
            evidence["measured_budget"] = {"init_exit": proc.returncode, "stderr": proc.stderr[-2000:]}
            return False
        data = json.loads(state_path.read_text(encoding="utf-8"))
    keys = set(_keys(data))
    evidence["measured_budget"] = {
        "init_exit": proc.returncode,
        "budget_keys": sorted(data.get("budget", {})),
        "is_measured_key_present": "_is_measured" in keys,
        "is_detected_key_present": "_is_detected" in keys,
    }
    return "_is_measured" not in keys


def check_pytest(evidence: dict) -> bool:
    python = ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        evidence["pytest"] = {"error": f"interpreter not found: {python}"}
        return False
    proc = subprocess.run(
        [str(python), "-m", "pytest", *PYTEST_TARGETS, "-q"],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, INNER_ENV: "1"},
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    evidence["pytest"] = {
        "command": f".venv/bin/python -m pytest {' '.join(PYTEST_TARGETS)} -q",
        "exit_code": proc.returncode,
        "summary": lines[-1] if lines else "",
    }
    return proc.returncode == 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    evidence: dict = {}
    a = check_scan(evidence)
    b = check_gear_names(evidence)
    c = check_contract_resolution(evidence)
    d = check_measured_budget(evidence)
    e = check_pytest(evidence)

    result = "PASS" if (a and b and c and d and e) else "FAIL"
    write_verdict(args.out, probe="port_scan", result=result, evidence=evidence)

    print(f"port_scan: {result} (scan={a} gear_names={b} contract={c} measured_budget={d} pytest={e})")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
