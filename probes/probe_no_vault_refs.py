#!/usr/bin/env python3
"""probes/probe_no_vault_refs.py — T10: nothing under the shipped tree
references the vault, the founder's own tooling, or the founder personally
by name (see the TERMS list below for exactly which strings), and
`bin/node_gates.py` resolves the acceptance contract from the package rather
than a home-directory path.

Scans `bin skills hyperspace ui probes tests` — wider than the T1.2 port
row's scan, which stops at bin/skills/hyperspace (this row deliberately
widens scope to the whole shipped-plus-test tree; the brief calls this out
explicitly). The same narrow, disclosed exclusion as `probe_no_nova_infra.py`
applies to the two files that exist solely to define/mirror this denylist —
see that module's docstring for the exact rule; nothing else is excused, and
a real finding (a personal name baked into the vendored UI bundle, or used as
a placeholder value in a test fixture) is reported here as a FAIL, never
patched by this row.

Usage: imported by probes/run.py; PROBE = "no_vault_refs"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402
from scan_tree import scan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROBE = "no_vault_refs"

SCANNED_DIRS = ["bin", "skills", "hyperspace", "ui", "probes", "tests"]
# Built by concatenation — this file lives under probes/, itself in scope.
# Every fragment below is checked (empirically, at authoring time) to contain
# none of the six terms, or a substring of any of them, contiguously — a
# 2-way split of the combined lowercase term was tried first and rejected:
# its first half alone still spelled out the shorter personal-name term in
# full, so the split below breaks that term apart too, not just this one.
TERMS = [
    "Nova" + "Caelum_Obs",
    "AGENTOS" + "_ROOT",
    "Agent" + "SecretBase",
    "Dan" + "iel",
    "Egh" + "dami",
    "dan" + "iel" + "egh" + "dami",
]

_DENYLIST_DEFINITION_FILES = {"probes/check_port_scan.py", "tests/test_port.py"}


def _is_denylist_definition_line(path_rel: str, term: str, text: str) -> bool:
    if path_rel not in _DENYLIST_DEFINITION_FILES:
        return False
    stripped = text.strip()
    return stripped in (f'"{term}",', f'"{term}"', f"'{term}',", f"'{term}'")


def _contract_resolution() -> dict:
    text = (ROOT / "bin" / "node_gates.py").read_text(encoding="utf-8")
    result = {
        "path_home_count": text.count("Path.home()"),
        "imports_package_contract": "hyperspace.contracts.candidate" in text,
    }
    result["ok"] = result["path_home_count"] == 0 and result["imports_package_contract"]
    return result


def run(out_dir, opts) -> bool:
    findings = scan(ROOT, SCANNED_DIRS, TERMS, case_insensitive=True)
    excluded, real = [], []
    for f in findings:
        rel = str(f.path)
        line = f"{rel}:{f.line}: [{f.term}] {f.text[:200]}"
        if _is_denylist_definition_line(rel, f.term, f.text):
            excluded.append(line)
        else:
            real.append(line)

    contract = _contract_resolution()

    ok = not real and contract["ok"]
    evidence = {
        "scan": {
            "dirs": SCANNED_DIRS, "terms": TERMS, "case_insensitive": True,
            "total_findings": len(findings), "real_findings": real,
            "excluded_denylist_definition_lines": excluded,
            "exclusion_rule": (
                "a bare quoted copy of the term, alone on its line, inside "
                "probes/check_port_scan.py or tests/test_port.py — the two files "
                "that exist to define/mirror this denylist and therefore contain "
                "every term as a literal by construction. Nothing else is excluded."
            ),
        },
        "contract_resolution": contract,
    }
    write_verdict(Path(out_dir) / f"{PROBE}.json", probe=PROBE, result="PASS" if ok else "FAIL", evidence=evidence)
    return ok
