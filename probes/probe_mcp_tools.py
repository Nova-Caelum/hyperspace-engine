#!/usr/bin/env python3
"""probes/probe_mcp_tools.py — T6: the stdio MCP server Claude Code spawns
per session lists the verifier's `complete_workitem` plus the six graph tools
the engine's own nodes call, and each answers a scripted call against a temp
store with no `isError`.

Composes `probes/check_mcp_stdio.py`'s live scripted session
(`check_live_smoke`) entirely — never re-implemented.

Usage: imported by probes/run.py; PROBE = "mcp_tools"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402
import check_mcp_stdio as cms  # noqa: E402

PROBE = "mcp_tools"


def run(out_dir, opts) -> bool:
    evidence: dict = {"required_tool_names": cms.REQUIRED_TOOL_NAMES}
    ok = cms.check_live_smoke(evidence)
    write_verdict(Path(out_dir) / f"{PROBE}.json", probe=PROBE, result="PASS" if ok else "FAIL", evidence=evidence)
    return ok
