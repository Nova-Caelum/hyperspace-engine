#!/usr/bin/env python3
"""Closed set of legal endings for a loop run (T3.5).

Task Graph: `nova-caelum-framework`, module `ncf-m3-state-layer`, row
`ncf-m3-kill-predicate`. PRD_NovaCaelumFramework_ChiefPM_2026-08-27.md
#9.1, verbatim:

    LoopStatus = "framing" | "understanding" | "deciding" | "specifying" |
                 "executing" | "verifying" |
                 "live" |                      # NOT terminal — awaiting
                                                # principal confirmation
                 "done" | "descoped" | "killed" |
                 "abandoned_budget" | "blocked_external"

    LEGITIMATE_TERMINAL = {"done", "descoped", "killed"}
    # abandoned_budget and blocked_external FIRE the kill path.

Four properties of `terminal_route()`, all load-bearing and copied
deliberately from the PRD: **deterministic and total** (always returns an
answer) · **cause-blind** (cause is recorded elsewhere; cause never gates
the route) · **system-code-only** — no agent-supplied field reaches it and
it accepts no route/outcome argument from any caller · **defined by an
allowlist of legitimate outcomes, never a denylist of failures.**

`LOOP_STATUS` moves here from `loop_state.py` (T3.1 kept it there per that
row's own handoff, pending this one). `loop_state.py` imports it from here
so there is exactly one copy — this module has no import of `loop_state`,
so the dependency is one-directional and there is no cycle.
"""

from __future__ import annotations

from typing import Any

LOOP_STATUS = (
    "framing", "understanding", "deciding", "specifying", "executing",
    "verifying", "live", "done", "descoped", "killed",
    "abandoned_budget", "blocked_external",
)

LEGITIMATE_TERMINAL = frozenset({"done", "descoped", "killed"})

# PRD #9.1: an unnoticed budget death is the loop's exact analogue of
# silent non-filing — both statuses fire the kill path rather than sitting
# unresolved.
KILL_TRIGGERS = frozenset({"abandoned_budget", "blocked_external"})


class IllegalEnding(ValueError):
    """Raised, never recorded, when a caller tries to end a run outside
    `LEGITIMATE_TERMINAL`, or violates a precondition an event verb in
    `loop_state.py` enforces (e.g. `confirm` without human authority)."""


def is_terminal(status: str) -> bool:
    """True iff `status` is one of the legitimate terminal endings.
    `live` is deliberately not terminal — it is awaiting principal
    confirmation (PRD #9.1)."""
    return status in LEGITIMATE_TERMINAL


def terminal_route(state: Any) -> str | None:
    """Derive this run's ending from its state alone.

    Deterministic and total: always returns one of `"killed"`,
    `"descoped"`, `"done"`, or `None`. Cause-blind: `kill["reason"]` and
    the descope decision's content are never read here, only their
    presence/absence — no field this function inspects can be supplied by
    an agent as an outcome request; each is written by one of the event
    verbs in `loop_state.py`, never by this predicate itself, and this
    predicate takes no route/outcome argument from any caller.

    `state` is a `LoopState` instance (read via its `.data` mapping) or a
    plain dict with the same shape — accepted so the predicate can be
    exercised directly against a minimal fixture in tests without needing
    a full valid document.

    Allowlist, in priority order (an out-of-set status can never reach
    here as a *route* — see `IllegalEnding` for how out-of-set endings are
    rejected instead of recorded):
      - "killed"    when kill.fired is True, OR status is in KILL_TRIGGERS
      - "descoped"  when a descope decision has been recorded
      - "done"      when status is "done"
      - None        otherwise — the run has not legitimately ended yet
    """
    data = state.data if hasattr(state, "data") else state
    status = data.get("status")
    kill = data.get("kill") or {}

    if kill.get("fired") or status in KILL_TRIGGERS:
        return "killed"
    if data.get("descope_decision_ref") is not None:
        return "descoped"
    if status == "done":
        return "done"
    return None
