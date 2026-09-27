#!/usr/bin/env python3
"""probes/probe_pydantic_graph.py — T8: the completion pipeline this plugin
ships executes as a real `pydantic_graph.Graph` with exactly the five named
nodes, and the package declares `pydantic-graph` and `pydantic-ai-slim` as
dependencies.

Usage: imported by probes/run.py; PROBE = "pydantic_graph"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROBE = "pydantic_graph"
EXPECTED_NODES = ["Commit", "CriteriaQuality", "EvidenceJudge", "Landing", "Vet"]


def run(out_dir, opts) -> bool:
    import pydantic_graph
    from pydantic_graph.step import NodeStep

    from hyperspace.verify.graph import verification_graph

    names = sorted(
        n.node_type.__name__ for n in verification_graph.nodes.values() if isinstance(n, NodeStep)
    )
    is_graph = isinstance(verification_graph, pydantic_graph.Graph)
    nodes_ok = names == EXPECTED_NODES

    with (ROOT / "pyproject.toml").open("rb") as f:
        deps = tomllib.load(f)["project"]["dependencies"]
    has_pydantic_graph = any(d.startswith("pydantic-graph") for d in deps)
    has_pydantic_ai = any(d.startswith("pydantic-ai-slim") for d in deps)

    ok = is_graph and nodes_ok and has_pydantic_graph and has_pydantic_ai
    evidence = {
        "is_pydantic_graph": is_graph,
        "graph_name": getattr(verification_graph, "name", None),
        "node_names": names,
        "expected_node_names": EXPECTED_NODES,
        "dependencies": deps,
        "has_pydantic_graph_dependency": has_pydantic_graph,
        "has_pydantic_ai_slim_dependency": has_pydantic_ai,
    }
    write_verdict(Path(out_dir) / f"{PROBE}.json", probe=PROBE, result="PASS" if ok else "FAIL", evidence=evidence)
    return ok
