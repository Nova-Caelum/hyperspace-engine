"""The local verifier: the five-step closure pipeline as a pydantic graph over
the local store. `complete_workitem(claim, local_deps(store, judge))` returns
exactly one of `done | refused | unverifiable | already_done`."""
from .claim import CompletionClaim, ManualAttestation, TouchedPath
from .deps import Deps, local_deps
from .graph import complete_workitem, verification_graph

__all__ = [
    "CompletionClaim", "Deps", "ManualAttestation", "TouchedPath",
    "complete_workitem", "local_deps", "verification_graph",
]
