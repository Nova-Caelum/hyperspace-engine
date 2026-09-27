#!/usr/bin/env python3
"""probes/probe_gear_names.py — T12: every node skill this plugin ships is
named `gear2-understand`..`gear6-live` (with `acing-hyperspace` as the
router), and no skill or agent text anywhere under `skills/`/`bin/` names an
`hs-*` skill.

Usage: imported by probes/run.py; PROBE = "gear_names"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROBE = "gear_names"

EXPECTED_SKILLS = {
    "acing-hyperspace", "gear2-understand", "gear3-decide",
    "gear4-draft", "gear5-build", "gear6-live", "hyperspace-setup",
}
REQUIRED_LOOP_SKILLS = {
    "acing-hyperspace", "gear2-understand", "gear3-decide",
    "gear4-draft", "gear5-build", "gear6-live",
}
HS_NAME = re.compile(r"\bhs-[a-z]")


def run(out_dir, opts) -> bool:
    skill_dirs = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    is_subset = skill_dirs <= EXPECTED_SKILLS
    loop_present = REQUIRED_LOOP_SKILLS <= skill_dirs

    hits: list[str] = []
    for base in ("skills", "bin"):
        for path in sorted((ROOT / base).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for n, line in enumerate(text.splitlines(), 1):
                if HS_NAME.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{n}")

    ok = is_subset and loop_present and not hits
    evidence = {
        "skill_dirs": sorted(skill_dirs),
        "expected_superset": sorted(EXPECTED_SKILLS),
        "skill_dirs_is_subset_of_expected": is_subset,
        "loop_skills_present": loop_present,
        "hs_name_scan": {"dirs": ["skills", "bin"], "pattern": r"\bhs-[a-z]", "hits": hits},
    }
    write_verdict(Path(out_dir) / f"{PROBE}.json", probe=PROBE, result="PASS" if ok else "FAIL", evidence=evidence)
    return ok
