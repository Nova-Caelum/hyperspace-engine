"""The acceptance contract, vendored into the package.

`bin/node_gates.py` imports `CandidateWorkItem` from here, so a gate never
reaches outside the installed plugin for it. Only `candidate` and `enums` are
vendored in this package today; see bin/PORT_NOTES.md.
"""
from .candidate import AcceptanceCriterion, CandidateWorkItem
from .enums import EffortLevel, VerificationKind, WorkItemState, WorkItemType

__all__ = [
    "AcceptanceCriterion",
    "CandidateWorkItem",
    "EffortLevel",
    "VerificationKind",
    "WorkItemState",
    "WorkItemType",
]
