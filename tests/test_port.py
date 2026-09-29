"""T1.2 — the engine port belongs to the product.

(a) no vault, infrastructure or personal reference under bin/, skills/,
    hyperspace/; (b) the six gear skill names and no `hs-` skill name;
(c) node_gates.py resolves the contract from the package, never the home
    directory; (d) a fresh state file carries only measured budget fields and
    still validates; (e) the port-scan check script writes PASS.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from probes.scan_tree import scan  # noqa: E402

SCANNED_DIRS = ["bin", "skills", "hyperspace"]
FORBIDDEN_TERMS = [
    "NovaCaelum_Obs",
    "AGENTOS_ROOT",
    "AgentSecretBase",
    "_agentOS",
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
#: Set by probes/check_port_scan.py on the pytest it runs, so (e) does not recurse.
INNER_ENV = "HYPERSPACE_PORT_SCAN_INNER"


def _keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _keys(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _keys(value)


def test_a_no_vault_infra_or_personal_references():
    findings = scan(ROOT, SCANNED_DIRS, FORBIDDEN_TERMS, case_insensitive=True)
    assert findings == [], "\n".join(f"{f.path}:{f.line}: [{f.term}] {f.text}" for f in findings)


def test_b_gear_skill_names_only():
    assert set(GEAR_SKILLS).issubset(os.listdir(ROOT / "skills"))
    hits = []
    for base in ("skills", "bin"):
        for path in sorted((ROOT / base).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if HS_NAME.search(line):
                        hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert hits == [], "\n".join(hits)


def test_c_node_gates_resolves_contract_from_package():
    text = (ROOT / "bin" / "node_gates.py").read_text(encoding="utf-8")
    assert "Path.home()" not in text
    assert FORBIDDEN_TERMS[0] not in text  # the vault root name
    assert "hyperspace.contracts.candidate" in text


def test_d_init_writes_measured_budget_fields_only(tmp_path):
    source = tmp_path / "original_input.md"
    source.write_text("port check\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "loop_state.py"), "init",
         "--goal", "port-check", "--input", str(source), "--workspace", str(tmp_path)],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads((tmp_path / "port-check" / "loop.state.json").read_text(encoding="utf-8"))
    keys = set(_keys(data))
    assert "_is_measured" not in keys
    assert "_is_detected" not in keys

    sys.path.insert(0, str(ROOT / "bin"))
    import loop_state  # noqa: PLC0415

    schema = json.loads((ROOT / "bin" / "loop_state.schema.json").read_text(encoding="utf-8"))
    assert loop_state.validate_against_schema(data, schema) == []


@pytest.mark.skipif(os.environ.get(INNER_ENV) == "1", reason="running inside check_port_scan.py")
def test_e_port_scan_check_writes_pass(tmp_path):
    out = tmp_path / "port_scan.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "probes" / "check_port_scan.py"), "--out", str(out)],
        capture_output=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    assert out.is_file(), proc.stdout + proc.stderr
    verdict = json.loads(out.read_text(encoding="utf-8"))
    assert verdict["result"] == "PASS", json.dumps(verdict["evidence"], indent=2)[:4000]


def _candidate(**overrides):
    payload = {
        "_comment": "annotation keys are stripped at every depth",
        "project": "demo",
        "external_id": "demo:goal-acceptance",
        "name": "Demo goal acceptance",
        "type": "task",
        "idempotency_key": "k1",
        "specification": {
            "_note": "stripped too",
            "problem": "The demo goal has no acceptance criteria written down anywhere yet.",
            "why_it_matters": "Without criteria the node cannot pass its gate and design cannot start.",
            "context_pointer": "01_understand/Problem.md in the run folder",
        },
        "source_references": [{"uri": "original_input.md"}],
        "effort_level": "quick",
        "module": None,
        "acceptance_criteria": [{
            "statement": "WHOLE-PATH: running the demo end to end writes out/result.txt",
            "verification": {"kind": "file_state", "path": "out/result.txt", "assertion": "exists"},
        }],
        "proposer_identity": "engineer",
        "proposer_surface": "cli",
        "uncertainty_notes": [],
    }
    payload.update(overrides)
    return payload


def test_validate_candidate_script(tmp_path):
    script = ROOT / "bin" / "validate_candidate.py"
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_candidate()), encoding="utf-8")
    ok = subprocess.run([sys.executable, str(script), str(good)], capture_output=True, encoding="utf-8", errors="replace")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "VALID" in ok.stdout

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_candidate(module="m", legacy_stated_type="task")), encoding="utf-8")
    refused = subprocess.run([sys.executable, str(script), str(bad)], capture_output=True, encoding="utf-8", errors="replace")
    assert refused.returncode == 1
    assert "INVALID" in refused.stdout
    assert "legacy_stated_type" in refused.stdout  # pydantic's own message, printed

    shipped = ROOT / "skills" / "gear2-understand" / "references" / "candidate-template.json"
    template = subprocess.run([sys.executable, str(script), str(shipped)], capture_output=True, encoding="utf-8", errors="replace")
    assert template.returncode == 0, template.stdout + template.stderr


def test_build_gate_accepts_the_plugins_closure_labels(tmp_path):
    sys.path.insert(0, str(ROOT / "bin"))
    import node_gates  # noqa: PLC0415

    workplan = tmp_path / "workplan.json"
    workplan.write_text(json.dumps({"project": "demo", "work_items": [{"external_id": "demo-a"}]}), encoding="utf-8")
    reconciliation = tmp_path / "RECONCILIATION.md"
    reconciliation.write_text("- demo-a → done\n", encoding="utf-8")
    verdicts = {}
    for label in ("hyperspace-verifier", "hyperspace-console", "graph-machine-committer"):
        snapshot = tmp_path / f"{label}.json"
        snapshot.write_text(json.dumps([{
            "external_id": "demo-a", "state": "done", "completed_by": label,
            "updated_at": "2026-09-26T00:00",
        }]), encoding="utf-8")
        verdicts[label] = node_gates.check_executing(
            workplan=workplan, verifications_dir=tmp_path / "none",
            reconciliation=reconciliation, graph_snapshot=snapshot,
        ).ok
    assert verdicts == {"hyperspace-verifier": True, "hyperspace-console": True,
                        "graph-machine-committer": False}
