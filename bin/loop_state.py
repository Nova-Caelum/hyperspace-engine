#!/usr/bin/env python3
"""Run-state file, reader and writer for a multi-session loop run (T3.1).

Task Graph: `nova-caelum-framework`, module `ncf-m3-state-layer`,
row `ncf-m3-state-object`. Gives a piece of multi-session work a
machine-readable file that answers, on resume, which stage it stopped in,
which gates it passed, how much budget it has burned, and how it ended —
instead of requiring a fresh session to read prose and guess.

Runtime files land at `workspace/<goal-slug>/loop.state.json` (D6). The shape
is declared in the sibling `loop_state.schema.json` and mirrors
`_agentOS/graph_library/contracts/run.py`'s `MachineRun` field-for-field
where meaning matches (`run_id`, `original_input`, `input_hash`, `status`,
`current_node`) — `framework_version` plays `machine_version`'s role, and
`status` uses PRD #9.1's `LoopStatus` set rather than `run.py`'s `RunStatus`
(the two enums diverge deliberately; see the T3.1 notes file's
field-mirroring table).

Validator note: `loader.py` (the M2 eval harness's fixture validator) is
hand-rolled stdlib, but its `validate()` is bespoke to one fixture shape —
closed-vocabulary parity checks against `fixture_schema.json`, not a generic
schema walker — so there is nothing generic in it to import. This module
therefore implements its own minimal draft-07 subset: `required`, `type`
(including `type` as a list, i.e. nullable fields), `enum`, `properties`,
and `items`. `minLength`/`pattern`/`format`/`additionalProperties` are not
enforced even where the schema file uses them for documentation only.

T3.2 (ncf-m3-artifact-freeze) adds `gate_pass()`/`check_frozen()`: freezing
is a step inside the gate check, not a hook on every file write.
`gate_pass()` runs `check_frozen()` first — recomputing sha256 for every
already-frozen artifact and bumping `budget.doubled_back_rounds` on any
mismatch it discovers unprompted — then hashes and records the artifacts
the passing node produced.

T3.5 (ncf-m3-kill-predicate) adds `record_kill()`/`descope()`/`confirm()`:
the only three ways a run may reach a terminal state. Each writes
`final_route` from `loop_terminal.terminal_route(state)` and nothing else
writes that field. `LOOP_STATUS`/`LEGITIMATE_TERMINAL` now live in
`loop_terminal.py` (single source); this module imports them.

Counter semantics beyond the doubled-back count (rework/pivot caps,
`_is_measured`/`_is_detected`, driver-approval recording, escape rate) are
T3.6's row — out of scope here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "loop_state.schema.json"
STATE_FILENAME = "loop.state.json"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import loop_terminal  # noqa: E402 — single source for LOOP_STATUS/LEGITIMATE_TERMINAL (T3.5)
import node_gates  # noqa: E402 — T4.8 node exit-gate check registry, consulted by gate-pass

# Re-exported for backward compatibility — LOOP_STATUS/LEGITIMATE_TERMINAL
# used to live here (T3.1); T3.5 moved the definitions to loop_terminal.py
# so there is exactly one copy. `loop_state.LOOP_STATUS` still resolves.
LOOP_STATUS = loop_terminal.LOOP_STATUS
LEGITIMATE_TERMINAL = loop_terminal.LEGITIMATE_TERMINAL

# T4.9 (loop-ending-executing-live-done, D1): the four stage nodes whose
# name `set_node` is allowed to mirror into `status`. `live` is deliberately
# excluded — it is a status the "executing" gate CONFERS (see `gate_pass`
# below), never a node a caller types their way into with `set-node`.
# `framing` is also excluded: `LoopState.init` sets `status`/`current_node`
# to "framing" directly (never through `set_node`), and no caller in this
# tree ever calls `set_node(..., "framing")` (verified 2026-09-17 by
# grepping every `set-node`/`set_node` call site under `_agentOS/`) — so
# cutting it from the mirror changes no existing behavior.
_STATUS_MIRROR_NODES = frozenset({"understanding", "deciding", "specifying", "executing"})


class LoopStateValidationError(ValueError):
    """Raised when a state document fails the schema's minimal draft-07 subset."""


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _check_type(value: Any, type_spec: Any) -> bool:
    """One `type` keyword check. `type_spec` may be a single string or a list."""
    if type_spec is None:
        return True
    types = type_spec if isinstance(type_spec, list) else [type_spec]
    for t in types:
        if t == "null" and value is None:
            return True
        if t == "string" and isinstance(value, str):
            return True
        if t == "boolean" and isinstance(value, bool):
            return True
        if t == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if t == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if t == "object" and isinstance(value, dict):
            return True
        if t == "array" and isinstance(value, list):
            return True
    return False


def validate_against_schema(
    instance: Any, schema: dict[str, Any], path: str = "$"
) -> list[str]:
    """Minimal draft-07 subset: `required`, `type`, `enum`, `properties`, `items`.

    Returns a list of human-readable error strings; an empty list means valid.
    Stops descending into a node once its own `type` check fails, so one bad
    field does not cascade into spurious child errors.
    """
    errors: list[str] = []

    if "type" in schema and not _check_type(instance, schema["type"]):
        errors.append(f"{path}: expected type {schema['type']!r}, got {type(instance).__name__}")
        return errors

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} is not one of {schema['enum']!r}")

    if isinstance(instance, dict):
        for required_key in schema.get("required", []):
            if required_key not in instance:
                errors.append(f"{path}: missing required property {required_key!r}")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                errors.extend(validate_against_schema(value, properties[key], f"{path}.{key}"))
    elif isinstance(instance, list):
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(instance):
                errors.extend(validate_against_schema(item, item_schema, f"{path}[{index}]"))

    return errors


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cap_block(*, cap: float | None, is_measured: bool, is_detected: bool) -> dict[str, Any]:
    return {"cap": cap, "used": 0, "_is_measured": is_measured, "_is_detected": is_detected}


# Daniel's four caps (Plan T3.6 note, 2026-08-27; PRD §6.3): one fresh
# session, one compaction, two real-time hours, three worklog entries, per
# task. Never invented here — set once, cited to source. All four ship
# `_is_measured: False` (PRD §6.3: Daniel's numbers are guesses, not
# measurements). `_is_detected` is True only for fresh_sessions/compactions
# — the SessionStart hook observes `startup`/`compact` events and can bump
# them; `daniel_hours`/`worklog_entries` are False because nothing in this
# system observes a real-time hour elapsing or a worklog append happening
# (PRD §6.2's own rule: an undetected cap is advisory, not a violation —
# the schema `description` on those two fields says so explicitly).
DANIEL_CAPS: dict[str, dict[str, Any]] = {
    "fresh_sessions": {"cap": 1, "is_measured": False, "is_detected": True},
    "compactions": {"cap": 1, "is_measured": False, "is_detected": True},
    "daniel_hours": {"cap": 2, "is_measured": False, "is_detected": False},
    "worklog_entries": {"cap": 3, "is_measured": False, "is_detected": False},
}

# Which SessionStart `source` bumps which cap. Any other source is a no-op
# (D4 — only detectable caps get detected).
_BUMP_EVENT_TO_CAP: dict[str, str] = {
    "startup": "fresh_sessions",
    "compact": "compactions",
}


def _default_budget() -> dict[str, Any]:
    budget: dict[str, Any] = {
        name: _cap_block(cap=spec["cap"], is_measured=spec["is_measured"], is_detected=spec["is_detected"])
        for name, spec in DANIEL_CAPS.items()
    }
    budget.update({
        "rework_rounds": 0,
        "doubled_back_rounds": 0,
        "doubled_back_events": [],
        "stage_retries": 0,
    })
    return budget


@dataclass
class LoopState:
    """Thin dict wrapper over one `loop.state.json`. Every mutating verb ends
    in `save()` — a run whose position only reaches storage at the end
    recovers from nothing (Plan T3.1 note)."""

    path: Path
    data: dict[str, Any]

    @classmethod
    def init(
        cls,
        *,
        goal_slug: str,
        workspace: Path | str,
        original_input: str,
        framework_version: str = "unknown",
        run_id: str | None = None,
    ) -> "LoopState":
        run_dir = Path(workspace) / goal_slug
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / STATE_FILENAME
        now = _now()
        data: dict[str, Any] = {
            "run_id": run_id or str(uuid.uuid4()),
            "goal_slug": goal_slug,
            "framework_version": framework_version,
            "original_input": original_input,
            "input_hash": hashlib.sha256(original_input.encode("utf-8")).hexdigest(),
            "status": "framing",
            "current_node": "framing",
            "trail": [{"node": "framing", "entered_at": now, "exited_at": None, "outcome": None}],
            "artifacts": [],
            "gates": [],
            "budget": _default_budget(),
            "driver": {"tier": None, "human_present": False, "authority": None},
            "kill": {"fired": False, "reason": None},
            "descope_decision_ref": None,
            "final_route": None,
            "escape_rate": None,
        }
        state = cls(path=path, data=data)
        state.save()
        return state

    @classmethod
    def load(cls, path: Path | str) -> "LoopState":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(path=path, data=data)

    def validate(self) -> None:
        errors = validate_against_schema(self.data, _load_schema())
        if errors:
            raise LoopStateValidationError("; ".join(errors))

    def save(self) -> None:
        """Atomic write: temp file in the same directory, then `os.replace`."""
        self.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(tmp_name, self.path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise

    def set_node(self, node: str) -> None:
        """Close the open trail entry (if any) and enter `node`. Rewrites
        the file immediately — this is a stage boundary, not the end.

        `status` follows `node` when `node` is one of the four stage nodes
        in `_STATUS_MIRROR_NODES` (`current_node` and `status` drift apart
        otherwise — a T4.8 gap found alongside the exit-gate wiring) —
        UNLESS the run has already reached a `LEGITIMATE_TERMINAL` status,
        or is currently `live`, either of which `set_node` must never move
        off of.

        `live` is deliberately NOT in `_STATUS_MIRROR_NODES` (D1,
        loop-ending-executing-live-done): it is a status the `executing`
        gate confers on a passing check, never a node this verb types a
        run into, and a run already sitting at `status: live` must not be
        silently downgraded back to a stage status by a stray `set-node`
        in a resumed session."""
        now = _now()
        trail = self.data.setdefault("trail", [])
        if trail and trail[-1].get("exited_at") is None:
            trail[-1]["exited_at"] = now
            if trail[-1].get("outcome") is None:
                trail[-1]["outcome"] = "advanced"
        trail.append({"node": node, "entered_at": now, "exited_at": None, "outcome": None})
        self.data["current_node"] = node
        current_status = self.data.get("status")
        if (
            node in _STATUS_MIRROR_NODES
            and current_status not in LEGITIMATE_TERMINAL
            and current_status != "live"
        ):
            self.data["status"] = node
        self.save()


# ─────────────────────────────────────────────────────────────────────────────
# T3.2 — artifact freeze (module-level functions: `f(state, ...)`, per the
# handoff's literal signatures — not LoopState methods).
# ─────────────────────────────────────────────────────────────────────────────


def check_frozen(state: "LoopState") -> list[dict[str, str]]:
    """Recompute sha256 for every already-frozen artifact. On a mismatch —
    content changed, or the file vanished — bump
    `budget.doubled_back_rounds` and append `{path, detected_at}` to
    `budget.doubled_back_events`, then save. No argument tells this
    function what changed; it discovers it by recomputing.

    Returns the mismatches detected THIS call (empty if none). Saves only
    when there is something to save — an unmodified run leaves the file
    untouched.
    """
    now = _now()
    mismatches: list[dict[str, str]] = []
    for artifact in state.data.get("artifacts", []):
        path = Path(artifact["path"])
        current_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        if current_hash != artifact["sha256"]:
            mismatches.append({"path": artifact["path"], "detected_at": now})

    if mismatches:
        budget = state.data.setdefault("budget", _default_budget())
        budget["doubled_back_rounds"] = budget.get("doubled_back_rounds", 0) + len(mismatches)
        budget.setdefault("doubled_back_events", []).extend(mismatches)
        state.save()

    return mismatches


def gate_pass(
    state: "LoopState",
    node: str,
    artifact_paths: list[str | Path],
    frozen_by: str,
) -> None:
    """A stage's exit gate has passed. `check_frozen(state)` runs FIRST —
    freezing is a gate action, so the doubled-back check belongs inside the
    gate check, not a hook firing on every file write (Plan T3.2 note).
    Then hash and record each artifact this node produced, and record the
    gate itself as passed.

    D1 (loop-ending-executing-live-done): a passing gate for the final
    stage node, `executing`, confers `status = "live"` — and leaves
    `current_node` unchanged, per the criterion's own wording. This
    function is only ever invoked by a caller that has already confirmed
    the gate passed (`loop_state.py gate-pass`'s CLI calls it only after
    `node_gates.run_check(...).ok` is True), so "a passing gate" and "this
    function ran" are the same event here — there is no separate success
    flag to branch on. No other node's gate touches `status`. Saves once
    at the end.
    """
    check_frozen(state)

    now = _now()
    for raw_path in artifact_paths:
        path = Path(raw_path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        state.data.setdefault("artifacts", []).append({
            "path": str(raw_path),
            "sha256": digest,
            "frozen_at": now,
            "frozen_by": frozen_by,
        })

    state.data.setdefault("gates", []).append({"node": node, "passed": True, "passed_at": now})
    if node == "executing":
        state.data["status"] = "live"
    state.save()


# ─────────────────────────────────────────────────────────────────────────────
# T3.6 — budget counters, driver record (module-level functions `f(state,
# ...)`, matching gate_pass()/check_frozen()'s style).
# ─────────────────────────────────────────────────────────────────────────────


def bump(state: "LoopState", event: str) -> int:
    """Increment the one Daniel cap the SessionStart hook can actually
    detect for this event (D4): `startup` bumps `fresh_sessions.used`,
    `compact` bumps `compactions.used`. Any other event is a no-op —
    returns 0 and does not save, because nothing changed. Returns the new
    `used` count on a real bump (always >= 1). A crossed cap is never
    reset here or anywhere else — bumping past `cap` keeps counting.

    Self-gates on terminal status (`done`/`descoped`/`killed`): a finished
    run's session/compaction count is frozen, so a no-op here is correct
    rather than a caller having to re-check `loop_terminal.is_terminal()`
    before calling. Lets the hook call `bump` unconditionally on every file
    in scope for `startup`/`compact`, before it reads the display line —
    the display and `notify()` then agree within one session's preload
    (bumping *after* the display read would show last session's numbers
    beside this session's notification)."""
    cap_name = _BUMP_EVENT_TO_CAP.get(event)
    if cap_name is None:
        return 0
    if loop_terminal.is_terminal(state.data.get("status")):
        return 0

    budget = state.data.setdefault("budget", _default_budget())
    cap_block = budget.setdefault(
        cap_name,
        _cap_block(
            cap=DANIEL_CAPS[cap_name]["cap"],
            is_measured=DANIEL_CAPS[cap_name]["is_measured"],
            is_detected=DANIEL_CAPS[cap_name]["is_detected"],
        ),
    )
    cap_block["used"] = cap_block.get("used", 0) + 1
    state.save()
    return cap_block["used"]


def notify(state: "LoopState") -> list[str]:
    """Check Daniel's four caps for crossing. Returns one line per crossed
    cap (`used > cap`, and `cap` is not None/unset) naming the cap and the
    used-over-cap figures — never raises, never mutates or saves state, and
    never changes `status` (crossing notifies; it does not block, D4).
    Uncrossed and unset (`cap: None`) caps are silent."""
    budget = state.data.get("budget", {}) or {}
    lines: list[str] = []
    for name in DANIEL_CAPS:
        block = budget.get(name) or {}
        cap = block.get("cap")
        used = block.get("used", 0)
        if cap is not None and used > cap:
            lines.append(f"{name}: {used}>{cap} (soft cap crossed — notify-only, D4)")
    return lines


def record_approval(
    state: "LoopState",
    *,
    tier: str | None,
    human_present: bool,
    authority: str | None,
) -> None:
    """Record who was driving at this approval (SystemShape §11.8: `tier`
    and `human_present` are meant to be derived from the registry/session
    elsewhere in the loop; this verb persists whatever the caller supplies
    as the current driver block). `authority` is granted by Daniel and
    never self-elected — this verb records the grant, it does not create
    or check one (`confirm()` is what checks it)."""
    state.data["driver"] = {"tier": tier, "human_present": human_present, "authority": authority}
    state.save()


# ─────────────────────────────────────────────────────────────────────────────
# T3.5 — the closed set of legal endings. Three event verbs; each is the
# ONLY code that writes `final_route`, and each writes it from
# `loop_terminal.terminal_route(state)` — never from a caller-supplied
# route/outcome argument (module-level functions, matching gate_pass()).
# ─────────────────────────────────────────────────────────────────────────────


def _ensure_not_already_ended(state: "LoopState") -> None:
    if state.data.get("final_route") is not None:
        raise loop_terminal.IllegalEnding(
            f"run already ended with final_route={state.data['final_route']!r}"
        )


def record_kill(state: "LoopState", reason: str) -> None:
    """Fire the kill path. `reason` is recorded on `kill.reason` for a
    human to read later — it is never consulted by the predicate, which
    routes to \"killed\" on `kill.fired` alone (cause-blind, PRD #9.1)."""
    _ensure_not_already_ended(state)
    state.data["kill"]["fired"] = True
    state.data["kill"]["reason"] = reason
    state.data["final_route"] = loop_terminal.terminal_route(state)
    state.save()


def descope(state: "LoopState", decision_ref: str) -> None:
    """Record a descope decision. `decision_ref` points to where the
    decision lives (PRD #9.3: 'the decision is recorded in loop.state.json,
    not remembered') — its content is never read by the predicate, only
    its presence."""
    _ensure_not_already_ended(state)
    state.data["descope_decision_ref"] = decision_ref
    state.data["final_route"] = loop_terminal.terminal_route(state)
    state.save()


def confirm(state: "LoopState", by: str, escaped: int = 0, caught: int = 0) -> None:
    """Move `live` to `done` — but only when authority is a human
    principal per the `driver` block. Authority to drive is granted by
    Daniel and never self-elected (Plan T3.6 note); this verb checks that
    grant, it does not create it — recording WHO holds authority is
    `record_approval()`'s row, so `by` is accepted for CLI-call symmetry
    with the other two event verbs but is not itself what authorizes the
    move.

    `escaped`/`caught` (T3.6): live -> done is the loop's one
    "finished -> confirmed" transition (PRD §9.1's `live` is finished-but-
    unconfirmed; `done` is Daniel-only and terminal), so this is the one
    place `escape_rate` is written — PRD §8.1's
    escaped ÷ (escaped + caught), or null when both are zero rather than a
    division by zero. Defaults are 0/0 (null) so existing callers that pass
    only `by` keep working unchanged.
    """
    _ensure_not_already_ended(state)
    if state.data.get("status") != "live":
        raise loop_terminal.IllegalEnding(
            f"confirm requires status='live', got {state.data.get('status')!r}"
        )
    driver = state.data.get("driver") or {}
    if driver.get("authority") != "human":
        raise loop_terminal.IllegalEnding(
            "confirm requires driver.authority == 'human' "
            "(authority is granted by Daniel, never self-elected)"
        )
    total = escaped + caught
    state.data["escape_rate"] = (escaped / total) if total > 0 else None
    state.data["status"] = "done"
    state.data["final_route"] = loop_terminal.terminal_route(state)
    state.save()


# ─────────────────────────────────────────────────────────────────────────────
# CLI — init / read / set-node / gate-pass / check / record-kill / descope /
# confirm / bump / notify / record-approval
# ─────────────────────────────────────────────────────────────────────────────


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"expected a boolean (true/false), got {value!r}")


def _cmd_init(args: argparse.Namespace) -> int:
    original_input = Path(args.input).read_text(encoding="utf-8")
    state = LoopState.init(
        goal_slug=args.goal,
        workspace=args.workspace,
        original_input=original_input,
        framework_version=args.framework_version,
    )
    print(str(state.path))
    return 0


def _cmd_read(args: argparse.Namespace) -> int:
    state = LoopState.load(args.path)
    print(json.dumps(state.data, indent=2, sort_keys=True))
    return 0


def _cmd_set_node(args: argparse.Namespace) -> int:
    state = LoopState.load(args.path)
    state.set_node(args.node)
    print(json.dumps(state.data, indent=2, sort_keys=True))
    return 0


def _cmd_gate_pass(args: argparse.Namespace) -> int:
    """T4.8 final closure: every node exits through a registered check.
    D6's fail-open branch (an unregistered node freezing without a check)
    ended 2026-09-08 — an unregistered `--node` is refused (exit 2) FIRST,
    before anything else is checked and before `LoopState.load` touches
    anything. Then the evidence-argument guards (usage errors, exit 2):
    `--node executing` requires `--workplan` AND `--reconciliation`
    (T4.9, the reconciliation gate — wired the same way `--workplan` is),
    `--node understanding` requires `--tests` (T4.3), `--node deciding`
    requires `--decision` (T4.4), `--node specifying` requires `--plan`
    (T4.5). Then the empty-artifact guard (D6a, exit 1) — unconditional
    now that every node carries a check, so it is no longer conditioned on
    `node_gates.CHECKS.get(...)`. Only then is the node's check run and,
    on pass, `LoopState.load`/`gate_pass()` reached. A refusal (exit 1) or
    HOLD (exit 3, Decision D — a verifier row reads `unverifiable`)
    freezes nothing and records nothing."""
    if args.node not in node_gates.CHECKS:
        print(
            f"gate-pass refuses node {args.node!r}: no exit check is registered for it — "
            "every node exits through a registered check (T4.8 final closure; D6's "
            "fail-open branch ended 2026-09-08)",
            file=sys.stderr,
        )
        return 2

    if args.node == "executing" and not args.workplan:
        print("gate-pass --node executing requires --workplan PATH (T4.8)", file=sys.stderr)
        return 2
    if args.node == "executing" and not args.reconciliation:
        print("gate-pass --node executing requires --reconciliation PATH (T4.9)", file=sys.stderr)
        return 2
    if args.node == "understanding" and not args.tests:
        print("gate-pass --node understanding requires --tests PATH (T4.3)", file=sys.stderr)
        return 2
    if args.node == "deciding" and not args.decision:
        print("gate-pass --node deciding requires --decision PATH (T4.4)", file=sys.stderr)
        return 2
    if args.node == "specifying" and not args.plan:
        print("gate-pass --node specifying requires --plan PATH (T4.5)", file=sys.stderr)
        return 2

    if not args.artifact:
        print(
            f"gate-pass refuses node {args.node!r}: empty --artifact list — an exit that "
            "freezes nothing cannot record passed: true (T4.8 D6a)",
            file=sys.stderr,
        )
        return 1

    evidence: dict[str, Any] = {}
    if args.node == "executing":
        evidence["workplan"] = Path(args.workplan)
        evidence["reconciliation"] = Path(args.reconciliation)
        evidence["verifications_dir"] = (
            Path(args.verifications_dir)
            if args.verifications_dir
            else node_gates.DEFAULT_VERIFICATIONS_DIR
        )
        if args.graph_snapshot:
            evidence["graph_snapshot"] = Path(args.graph_snapshot)
    if args.node == "understanding":
        evidence["tests"] = Path(args.tests)
    if args.node == "deciding":
        evidence["decision"] = Path(args.decision)
    if args.node == "specifying":
        evidence["plan"] = Path(args.plan)

    result = node_gates.run_check(args.node, **evidence)
    if not result.ok:
        for message in result.messages:
            print(message, file=sys.stderr)
        return 3 if result.hold else 1

    state = LoopState.load(args.path)
    gate_pass(state, node=args.node, artifact_paths=args.artifact, frozen_by=args.by)
    print(json.dumps(state.data, indent=2, sort_keys=True))
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    state = LoopState.load(args.path)
    mismatches = check_frozen(state)
    print(json.dumps(
        {"mismatches": mismatches, "doubled_back_rounds": state.data["budget"]["doubled_back_rounds"]},
        indent=2, sort_keys=True,
    ))
    return 0


def _cmd_record_kill(args: argparse.Namespace) -> int:
    state = LoopState.load(args.path)
    record_kill(state, reason=args.reason)
    print(json.dumps(state.data, indent=2, sort_keys=True))
    return 0


def _cmd_descope(args: argparse.Namespace) -> int:
    state = LoopState.load(args.path)
    descope(state, decision_ref=args.decision_ref)
    print(json.dumps(state.data, indent=2, sort_keys=True))
    return 0


def _cmd_confirm(args: argparse.Namespace) -> int:
    state = LoopState.load(args.path)
    confirm(state, by=args.by, escaped=args.escaped, caught=args.caught)
    print(json.dumps(state.data, indent=2, sort_keys=True))
    return 0


def _cmd_bump(args: argparse.Namespace) -> int:
    state = LoopState.load(args.path)
    bump(state, event=args.event)
    print(json.dumps(state.data, indent=2, sort_keys=True))
    return 0


def _cmd_notify(args: argparse.Namespace) -> int:
    state = LoopState.load(args.path)
    for line in notify(state):
        print(line)
    return 0


def _cmd_record_approval(args: argparse.Namespace) -> int:
    state = LoopState.load(args.path)
    record_approval(state, tier=args.tier, human_present=args.human_present, authority=args.authority)
    print(json.dumps(state.data, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read/write the T3.1 run-state file (loop.state.json)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create a new loop.state.json for a goal.")
    p_init.add_argument("--goal", required=True, help="goal-slug; also the run's directory name")
    p_init.add_argument("--input", required=True, help="path to a file holding the raw original_input text")
    p_init.add_argument("--workspace", required=True, help="parent directory; state lands at <workspace>/<goal>/loop.state.json")
    p_init.add_argument("--framework-version", default="unknown", dest="framework_version")
    p_init.set_defaults(func=_cmd_init)

    p_read = sub.add_parser("read", help="Print a loop.state.json as JSON.")
    p_read.add_argument("path")
    p_read.set_defaults(func=_cmd_read)

    p_set_node = sub.add_parser("set-node", help="Record a stage-boundary transition.")
    p_set_node.add_argument("path")
    p_set_node.add_argument("--node", required=True)
    p_set_node.set_defaults(func=_cmd_set_node)

    p_gate_pass = sub.add_parser(
        "gate-pass", help="Consult the node's exit check, then freeze the artifacts a node just produced."
    )
    p_gate_pass.add_argument("path")
    p_gate_pass.add_argument("--node", required=True)
    p_gate_pass.add_argument(
        "--artifact", required=False, nargs="*", default=[],
        help="zero or more artifact file paths (none needed when the gate refuses)",
    )
    p_gate_pass.add_argument("--by", required=True, help="identity that froze these artifacts")
    p_gate_pass.add_argument(
        "--workplan", default=None,
        help="T4.8: path to the N3 workplan JSON; required when --node executing",
    )
    p_gate_pass.add_argument(
        "--reconciliation", default=None,
        help=(
            "T4.9 (loop-ending-executing-live-done): path to the run's "
            "reconciliation artifact naming every workplan row's disposition "
            "(done/deferred/archived/live-test); required when --node executing"
        ),
    )
    p_gate_pass.add_argument(
        "--verifications-dir", default=None, dest="verifications_dir",
        help="T4.8: verifier run-files directory (default: node_gates.DEFAULT_VERIFICATIONS_DIR)",
    )
    p_gate_pass.add_argument(
        "--graph-snapshot", default=None, dest="graph_snapshot",
        help=(
            "closure-identity source (2026-09-18): a saved `list_work_items` "
            "JSON payload for the project. When given, a `done` row's closure "
            "is judged by the graph's `completed_by` (the door that closed it) "
            "rather than inferred from local verifier run files. Omit for the "
            "original behaviour."
        ),
    )
    p_gate_pass.add_argument(
        "--tests", default=None,
        help="T4.3: path to N1's tests.json; required when --node understanding",
    )
    p_gate_pass.add_argument(
        "--decision", default=None,
        help="T4.4: path to N2's mapping.json; required when --node deciding",
    )
    p_gate_pass.add_argument(
        "--plan", default=None,
        help="T4.5: path to N3's Plan.md with task_ids backfilled by the uploader; required when --node specifying",
    )
    p_gate_pass.set_defaults(func=_cmd_gate_pass)

    p_check = sub.add_parser(
        "check", help="Recompute hashes for already-frozen artifacts; report doubled-back detections."
    )
    p_check.add_argument("path")
    p_check.set_defaults(func=_cmd_check)

    p_record_kill = sub.add_parser("record-kill", help="Fire the kill path. Cause is recorded; cause never gates.")
    p_record_kill.add_argument("path")
    p_record_kill.add_argument("--reason", required=True)
    p_record_kill.set_defaults(func=_cmd_record_kill)

    p_descope = sub.add_parser("descope", help="Record a descope decision.")
    p_descope.add_argument("path")
    p_descope.add_argument("--decision", required=True, dest="decision_ref", help="path to the recorded decision")
    p_descope.set_defaults(func=_cmd_descope)

    p_confirm = sub.add_parser(
        "confirm", help="Move status live -> done. Requires driver.authority == 'human'."
    )
    p_confirm.add_argument("path")
    p_confirm.add_argument("--by", required=True, help="confirming identity")
    p_confirm.add_argument(
        "--escaped", type=int, default=0,
        help="defects Daniel's principal-stage caught that our tests missed (PRD §8.1)",
    )
    p_confirm.add_argument(
        "--caught", type=int, default=0,
        help="defects our own tests caught before Daniel saw them (PRD §8.1)",
    )
    p_confirm.set_defaults(func=_cmd_confirm)

    p_bump = sub.add_parser(
        "bump", help="Increment a detected budget cap for one SessionStart event (startup|compact; anything else is a no-op)."
    )
    p_bump.add_argument("path")
    p_bump.add_argument("--event", required=True, help="SessionStart source, e.g. startup|compact|resume|clear")
    p_bump.set_defaults(func=_cmd_bump)

    p_notify = sub.add_parser(
        "notify", help="Print one line per crossed Daniel cap. Never blocks; exits 0 always."
    )
    p_notify.add_argument("path")
    p_notify.set_defaults(func=_cmd_notify)

    p_record_approval = sub.add_parser(
        "record-approval", help="Record who was driving at this approval (SystemShape §11.8)."
    )
    p_record_approval.add_argument("path")
    p_record_approval.add_argument("--tier", required=True, help="agent tier at this approval")
    p_record_approval.add_argument(
        "--human-present", required=True, dest="human_present", type=_parse_bool,
        help="true|false — was a human present at this approval",
    )
    p_record_approval.add_argument("--authority", required=True, help="who holds authority to drive")
    p_record_approval.set_defaults(func=_cmd_record_approval)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
