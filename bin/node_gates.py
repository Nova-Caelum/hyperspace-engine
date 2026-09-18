#!/usr/bin/env python3
"""Node exit-gate check registry (T4.8, `ncf-m4-exit-gate-completion`).

Decision: `AgentSecretBase/workspace/hyperspace-engine_new_sprintframework/
m4-loop/ExitGateDecision_T4.8_ChiefPM_2026-09-06.md` (D5/D5a in the sibling
`DECISIONS.md`). An exit gate is how a node proves it is finished; for the
Build node (`executing`) the only fresh evidence is the independent
verifier's own persisted run files under
`~/NovaCaelum_code/graph-machine/run/verifications/<run_id>.json` — never an
agent's claim. `loop_state.py gate-pass` consults `run_check()` here BEFORE
it writes anything (D5a: folded into `gate-pass`, no standalone
`exit_gate.py` — `overbloat-review` returned `shrink:`).

`CHECKS` is a registry, `node -> callable`. Step 0 implements `executing`;
`understanding` registers with T4.3 (`check_understanding`, below);
`deciding` with T4.4 (`check_deciding`, below); `specifying` with T4.5
(`check_specifying`, below) — the four stage nodes are all registered.
Only nodes outside the four (e.g. `verifying`) remain unregistered until
T4.8's final closure deletes the permissive branch: a node absent from
`CHECKS` has no exit check yet — `run_check()` returns `None` and the
caller keeps today's freeze-and-record behaviour (D6, time-bounded
fail-open, disclosed).

Stdlib at module level, plus the live contract where needed (D5a): the
`understanding` check imports `graph_library.contracts.candidate` LAZILY,
inside the function, so `check_executing` and its tests never load
pydantic. The `deciding` check reads raw JSON and markdown only — no
contract, no third import path. The `specifying` check reads the Plan as
markdown text through the sibling `plan_lint` parser (imported lazily,
stdlib only) — no contract, no MCP, no lint rule. No network.
"""

from __future__ import annotations

import json
import json as _j
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

#: Default location of the verifier's persisted run files. Overridable via
#: `loop_state.py gate-pass --verifications-dir`.
DEFAULT_VERIFICATIONS_DIR = (
    Path.home() / "NovaCaelum_code" / "graph-machine" / "run" / "verifications"
)

#: `final_result.outcome` values that count as a passing closure (ExitGateDecision
#: table, N4 row: `final_result.outcome in {done, already_done}`).
_PASSING_OUTCOMES = frozenset({"done", "already_done"})


@dataclass
class GateResult:
    """One node-check verdict. `ok=True` passes the gate outright.
    `ok=False, hold=True` is Decision D's HOLD (>=1 row `unverifiable`,
    none missing/refused) — exit 3, awaiting Daniel's attestation.
    `ok=False, hold=False` is an ordinary refusal — exit 1."""

    ok: bool
    hold: bool
    messages: list[str] = field(default_factory=list)


def _load_json_object(path: Path) -> dict[str, Any] | None:
    """Read one JSON file as a dict, or `None` on any read/parse failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _load_verification_file(path: Path) -> dict[str, Any] | None:
    """Same as `_load_json_object`, but a failure here is a SKIP, not a
    refusal — one unreadable/non-JSON file in the verifications directory
    never crashes the check and never poisons another row's evidence
    (handoff case h). Prints one diagnostic line to stderr; never raises."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"node_gates: skipping unreadable verification file {path}: {exc}", file=sys.stderr)
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"node_gates: skipping non-JSON verification file {path}: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f"node_gates: skipping verification file with non-object top level: {path}", file=sys.stderr)
        return None
    return data


def _latest_verification(
    verifications_dir: Path, project: str, external_id: str
) -> tuple[Path, dict[str, Any]] | None:
    """The newest `*.json` under `verifications_dir` (by `updated_at`,
    lexicographic ISO-8601 comparison) whose `external_id` and `project`
    match. Newest wins when more than one file names the same row —
    e.g. a `refused`/`unverifiable` attempt superseded by a later `done`
    (handoff case d). Unreadable/non-JSON files are skipped, not fatal."""
    best: tuple[Path, dict[str, Any], str] | None = None
    if not verifications_dir.is_dir():
        return None
    for path in sorted(verifications_dir.glob("*.json")):
        data = _load_verification_file(path)
        if data is None:
            continue
        if data.get("external_id") != external_id or data.get("project") != project:
            continue
        updated_at = str(data.get("updated_at") or "")
        if best is None or updated_at > best[2]:
            best = (path, data, updated_at)
    if best is None:
        return None
    return best[0], best[1]


def _row_passes(run: dict[str, Any]) -> bool:
    """ExitGateDecision N4 row, verbatim: `status: done`, `final_result.outcome
    in {done, already_done}`, `final_result.readback_state: done`."""
    final_result = run.get("final_result")
    if not isinstance(final_result, dict):
        final_result = {}
    return (
        run.get("status") == "done"
        and final_result.get("outcome") in _PASSING_OUTCOMES
        and final_result.get("readback_state") == "done"
    )


def _landing_verdicts(run: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The row's `steps.landing.data.verdicts` list, or `None` if that path
    is absent or malformed. Real shape verified 2026-09-17 against live
    files under `DEFAULT_VERIFICATIONS_DIR` (e.g. run
    `96c4c071-cbae-48fb-a3dc-30421e2dfa0e`, external_id `ncf-m4-primer`):
    each verdict is a dict with `statement`, `kind`, `discharged`, `failed`,
    `uncertain`, `evidence`. A row whose `unverifiable` outcome came from an
    earlier step (e.g. `vet` failing to resolve `acceptance_criteria_ref` —
    run `b506fa59-6a7f-41a3-9311-f2934b1e40a6`) never reaches `landing` at
    all, so `steps` has no `landing` key — that case returns `None` here,
    same as any other malformed shape."""
    steps = run.get("steps")
    if not isinstance(steps, dict):
        return None
    landing = steps.get("landing")
    if not isinstance(landing, dict):
        return None
    data = landing.get("data")
    if not isinstance(data, dict):
        return None
    verdicts = data.get("verdicts")
    if not isinstance(verdicts, list) or not verdicts:
        return None
    return verdicts


#: A reconciliation-artifact disposition line: a markdown bullet naming one
#: workplan row's `external_id` and its disposition token. Anything after
#: the disposition word — free-form notes on where the work landed — is
#: ignored by this parser; it exists for Daniel and the next agent, not
#: for the check. Format: `- <external_id> → <disposition>[ ...notes]`.
#: The four tokens are exhaustive by construction: the alternation IS the
#: validation, so a typo'd disposition simply fails to match and its row
#: reads as absent from the artifact (fails closed, never a silent pass).
_RECONCILIATION_LINE = re.compile(
    r"^\s*-\s*(?P<eid>\S+)\s+→\s+(?P<disposition>done|deferred|archived|live-test)\b"
)

#: The only disposition that may leave a row open through the gate — the
#: live-test row itself, whose work cannot start until the run is live.
_LIVE_TEST_DISPOSITION = "live-test"
#: Descoped work: passes without ever needing a verifier `done`.
_SKIP_VERIFIER_DISPOSITIONS = frozenset({"deferred", "archived"})

#: Role labels written to `work_items.completed_by` by the ops-server, one
#: per door. They are ROLE labels, never client ids or key material.
#:
#: Why a label is sufficient: every path that can set `state="done"`
#: stamps the door it came through. Five doors, three labels (verified
#: empirically 2026-09-18, ops-server 0.9.17 — the CREATE half of the
#: done guard was closed the same day after a probe found a candidate-
#: shaped CREATE landing an unverified `done` under any fleet key).
#:
#: Only two labels are evidence of a legitimate closure HERE. The third,
#: `workplan-uploader`, is a batch plan-ingest door that checks identity
#: but refuses nothing on state, so a plan may declare a row already
#: finished and it lands unverified. That is not a closure this gate may
#: accept, and it refuses BY NAME rather than falling through the
#: unknown-label branch — the difference between "a door we know does
#: not verify" and "a door that did not exist when this was written".
_COMMITTER_LABEL = "graph-machine-committer"
_CONSOLE_LABEL = "caelos-console"
#: Known door, NOT evidence of verification — see above.
_UPLOADER_LABEL = "workplan-uploader"

#: Sentinel: legitimate-so-far, but the label proves nothing — fall back
#: to the verifier-run check that predates stamping.
_PRE_STAMPING = "__pre_stamping__"

#: The oldest verifier run on disk, and therefore the moment before which
#: no row COULD carry a committer closure. A `done` row with no
#: `completed_by` whose `updated_at` predates this was closed when no
#: other door existed; refusing it would be refusing history, and no
#: amount of re-verification can repair it (the verifier discharges
#: against a delta since filing, and that delta is gone). A `done` row
#: with no `completed_by` updated AFTER this is a real miss and refuses.
_VERIFIER_EPOCH = "2026-09-06T00:31"

#: When STAMPING shipped (ops-server 0.9.17, this Mac's deploy). Before
#: this instant no row COULD carry a `completed_by`, whoever closed it —
#: so a null label is not evidence of anything and the gate falls back to
#: the original verifier-run check for those rows.
#:
#: These are TWO DIFFERENT EPOCHS and conflating them was a real bug:
#: keying the grandfather rule on _VERIFIER_EPOCH alone refused 27 rows
#: that the verifier itself had closed between 2026-09-06 and 2026-09-18,
#: purely because stamping did not exist yet to record it. Caught by
#: simulating the gate against the live graph before running it.
_STAMPING_EPOCH = "2026-09-18T06:30"


def _load_graph_snapshot(path: Path) -> dict[str, dict] | None:
    """`external_id -> row` from a saved `list_work_items` payload, or
    `None` if it cannot be read as a list of row objects.

    The snapshot is a local file the agent fetches from the graph, at the
    same trust level as `verifications_dir`: both catch mistakes, neither
    pretends to stop a determined forger.
    """
    try:
        data = _j.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    rows: dict[str, dict] = {}
    for row in data:
        if isinstance(row, dict) and row.get("external_id"):
            rows[str(row["external_id"])] = row
    return rows


def _closure_verdict(external_id: str, row: dict | None) -> tuple[bool, str]:
    """Is this row's `done` legitimate according to the graph? Returns
    `(ok, message)`; `message` is empty when ok."""
    if row is None:
        return False, (
            f"{external_id}: declared done but absent from the graph snapshot "
            "— the row does not exist, or the snapshot covers the wrong project"
        )
    state = str(row.get("state") or "")
    if state != "done":
        return False, (
            f"{external_id}: declared done in the reconciliation artifact but the "
            f"graph reads {state!r} — fix the row, never the artifact"
        )
    completed_by = row.get("completed_by")
    if completed_by in (_COMMITTER_LABEL, _CONSOLE_LABEL):
        return True, ""
    if completed_by == _UPLOADER_LABEL:
        return False, (
            f"{external_id}: closed by {_UPLOADER_LABEL!r} — the workplan-ingest door "
            "checks identity but verifies nothing, so a plan declaring a row already "
            "finished lands it unverified. Close it through the verifier, or mark it "
            "done in Caelos if you have confirmed it yourself"
        )
    if completed_by:
        return False, (
            f"{external_id}: completed_by is {completed_by!r} — an unrecognised door. "
            f"This gate accepts {_COMMITTER_LABEL!r} and {_CONSOLE_LABEL!r}"
        )
    updated_at = str(row.get("updated_at") or "")
    if updated_at and updated_at >= _STAMPING_EPOCH:
        return False, (
            f"{external_id}: done with no completed_by and updated_at {updated_at} "
            f"— every closure after {_STAMPING_EPOCH} is stamped by the door that made "
            "it, so this row reached done by no door the server knows"
        )
    # Closed before stamping existed: the label is unrecoverable, so defer
    # to the original evidence. UNVERIFIED here means "ask the run files",
    # not "pass" — the caller runs the pre-snapshot check for these.
    return True, _PRE_STAMPING



def _parse_reconciliation(path: Path) -> dict[str, str] | None:
    """`external_id -> disposition` for every matching bullet line in the
    reconciliation artifact, or `None` if the file cannot be read at all.
    A line that does not match `_RECONCILIATION_LINE` — a blank line, a
    markdown heading, free prose narrating the run — is silently skipped;
    not every line in the artifact is a disposition. A later bullet for
    the same `external_id` overwrites an earlier one, so a correction is
    a new line, never an in-place edit requirement."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    dispositions: dict[str, str] = {}
    for line in text.splitlines():
        match = _RECONCILIATION_LINE.match(line)
        if match:
            dispositions[match.group("eid")] = match.group("disposition")
    return dispositions


def _undischarged_manual_lines(external_id: str, run: dict[str, Any]) -> list[str]:
    """Enumeration lines for the HOLD message (loop-ending-executing-live-done,
    reconciliation gate, 2026-09-17): one line per undischarged-or-failed
    `manual` verdict in `run`'s landing step, each exactly `<external_id>
    → <the manual criterion's exact statement>` — the format an agent
    walks row-by-row when only Daniel's own attestation is outstanding.
    Returns `[]` when the row has no landing verdicts at all (e.g. a
    `vet`-stage failure that never reached `landing`) or none are an
    undischarged/failed `manual` kind — that case falls through to the
    generic 'unverifiable' message below, unchanged."""
    verdicts = _landing_verdicts(run)
    if verdicts is None:
        return []
    lines: list[str] = []
    for verdict in verdicts:
        if not isinstance(verdict, dict) or verdict.get("kind") != "manual":
            continue
        if verdict.get("failed") or not verdict.get("discharged"):
            lines.append(f"{external_id} → {verdict.get('statement', '')}")
    return lines


def check_executing(
    workplan: Path,
    verifications_dir: Path,
    reconciliation: Path,
    graph_snapshot: Path | None = None,
) -> GateResult:
    """The Build node's exit check (Step 0 of T4.8; reconciliation gate,
    T4.9/loop-ending-executing-live-done, 2026-09-17 — replaces the D2
    manual-only-HOLD narrowing Daniel reversed the same day: an
    undischarged `manual` verdict is a failure to tell him built work was
    ready for review, not a free pass).

    Every workplan `external_id` must carry a disposition in the
    reconciliation artifact: `done`, `deferred`, `archived`, or
    `live-test`. A row absent from the artifact refuses outright — the
    T5.3 hole this check exists to close: a row that looked done and was
    never actually closed. `deferred` and `archived` rows pass without
    ever needing a verifier `done` — they are descoped, not built, so
    nothing here checks their verifier state at all. `live-test` is the
    ONLY disposition that may cross the gate open; like deferred/archived
    it is exempt from the verifier check below (its work cannot begin
    until the run is live).

    A `done` row runs the ORIGINAL (pre-D2) verifier check, byte-for-byte:
    its run file must read `done` (`_row_passes`) or the row refuses/holds
    exactly as it always has — every undischarged executable criterion
    (`command_check`, `file_state`, `db_readback`, `http_readback`) still
    holds or refuses precisely as before; the reconciliation artifact
    cannot rescue those, regardless of what disposition it claims. The one
    addition: whenever a `done` row's verifier status is `unverifiable`
    and its landing verdicts carry an undischarged or failed `manual`
    verdict, that criterion's exact statement is enumerated
    (`_undischarged_manual_lines`) into the HOLD message — the agenda an
    agent hands Daniel to close it.
    """
    workplan_data = _load_json_object(Path(workplan))
    if workplan_data is None:
        return GateResult(ok=False, hold=False, messages=[f"workplan unreadable or invalid JSON: {workplan}"])

    project = str(workplan_data.get("project") or "")
    raw_items = workplan_data.get("work_items")
    rows = raw_items if isinstance(raw_items, list) else []
    external_ids = [
        str(row["external_id"]) for row in rows
        if isinstance(row, dict) and row.get("external_id")
    ]
    if not external_ids:
        return GateResult(ok=False, hold=False, messages=["workplan declares no work_items with an external_id"])

    reconciliation = Path(reconciliation)
    dispositions = _parse_reconciliation(reconciliation)
    if dispositions is None:
        return GateResult(
            ok=False, hold=False,
            messages=[f"reconciliation artifact unreadable: {reconciliation}"],
        )

    graph_rows: dict[str, dict] | None = None
    if graph_snapshot is not None:
        graph_rows = _load_graph_snapshot(Path(graph_snapshot))
        if graph_rows is None:
            return GateResult(
                ok=False, hold=False,
                messages=[f"graph snapshot unreadable or not a list of rows: {graph_snapshot}"],
            )

    verifications_dir = Path(verifications_dir)
    messages: list[str] = []
    any_missing_or_refused = False
    any_unverifiable = False

    for external_id in external_ids:
        disposition = dispositions.get(external_id)
        if disposition is None:
            messages.append(
                f"{external_id}: no disposition in reconciliation artifact {reconciliation} "
                "— every workplan row must be done, deferred, archived, or live-test"
            )
            any_missing_or_refused = True
            continue

        if disposition == _LIVE_TEST_DISPOSITION:
            continue  # the only disposition that may cross the gate open
        if disposition in _SKIP_VERIFIER_DISPOSITIONS:
            continue  # descoped work — passes without a verifier `done`

        # disposition == "done" (the regex admits no other token here).
        #
        # With a graph snapshot, the gate asks the SOURCE OF TRUTH who
        # closed the row instead of inferring it from local files. A
        # committer closure still consults the verifier run below, so an
        # undischarged `manual` criterion HOLDs exactly as Daniel's
        # reversal requires. A console closure is Daniel's own hand: he
        # IS the discharge of a manual criterion, so it passes outright.
        if graph_rows is not None:
            ok, message = _closure_verdict(external_id, graph_rows.get(external_id))
            if not ok:
                messages.append(message)
                any_missing_or_refused = True
                continue
            if message == _PRE_STAMPING:
                # Closed before stamping existed. The label proves nothing,
                # so the ORIGINAL evidence decides — with one carve-out: a
                # row closed before the verifier itself existed can have no
                # run file, ever, and refusing it would be refusing history.
                updated_at = str((graph_rows.get(external_id) or {}).get("updated_at") or "")
                if (
                    _latest_verification(verifications_dir, project, external_id) is None
                    and updated_at
                    and updated_at < _VERIFIER_EPOCH
                ):
                    continue
            elif (graph_rows.get(external_id) or {}).get("completed_by") == _CONSOLE_LABEL:
                continue
            else:
                found = _latest_verification(verifications_dir, project, external_id)
                if found is None:
                    continue  # committer-closed; run file simply not on this Mac
                path, run = found
                if not _row_passes(run) and run.get("status") == "unverifiable":
                    manual = _undischarged_manual_lines(external_id, run)
                    if manual:
                        messages.extend(manual)
                        messages.append(
                            f"{external_id}: verifier status is 'unverifiable' in {path.name} "
                            "— awaiting Daniel's attestation (Decision D)"
                        )
                        any_unverifiable = True
                continue
        found = _latest_verification(verifications_dir, project, external_id)
        if found is None:
            messages.append(f"{external_id}: no verifier run found under {verifications_dir}")
            any_missing_or_refused = True
            continue
        path, run = found
        if _row_passes(run):
            continue
        status = run.get("status")
        if status == "unverifiable":
            messages.extend(_undischarged_manual_lines(external_id, run))
            messages.append(
                f"{external_id}: verifier status is 'unverifiable' in {path.name} "
                "— awaiting Daniel's attestation (Decision D)"
            )
            any_unverifiable = True
        else:
            messages.append(f"{external_id}: verifier status is {status!r} in {path.name} — not done")
            any_missing_or_refused = True

    if not messages:
        return GateResult(ok=True, hold=False, messages=[])
    if any_missing_or_refused:
        return GateResult(ok=False, hold=False, messages=messages)
    # Every non-passing row is unverifiable, none missing/refused: HOLD.
    return GateResult(ok=False, hold=True, messages=messages)


# ─────────────────────────────────────────────────────────────────────────────
# T4.3 — the Understand node's exit check
# ─────────────────────────────────────────────────────────────────────────────

#: A whole-path criterion is marked by its `statement` beginning `WHOLE-PATH:`
#: (ledger ruling 2026-09-07: case-insensitive, leading whitespace allowed —
#: `AcceptanceCriterion` forbids extra fields, so the marker travels inside
#: the statement and into the filed row).
_WHOLE_PATH_MARKER = re.compile(r"^\s*WHOLE-PATH:", re.IGNORECASE)

_C10_REFUSAL = (
    "C10: no machine-checkable criterion — an all-manual test set cannot pass "
    "its own N1 gate"
)
_WHOLE_PATH_REFUSAL = (
    "no WHOLE-PATH: criterion — at least one criterion must exercise the whole "
    "path from entry to finish (SystemShape §11.9; PRD C10/C12)"
)


def _agentos_root() -> Path:
    """Where the live contract lives: env `AGENTOS_ROOT` if set; else this
    file's `_agentOS` (two levels up from `system/bin/`) when the contract is
    present there; else the canonical vault path."""
    override = os.environ.get("AGENTOS_ROOT")
    if override:
        return Path(override)
    local = Path(__file__).resolve().parents[2]
    if (local / "graph_library" / "contracts" / "candidate.py").is_file():
        return local
    return Path.home() / "NovaCaelum_Obs" / "_agentOS"


def _strip_annotations(obj: Any) -> Any:
    """Drop `_`-prefixed annotation keys at EVERY depth (copied from
    `taskgraph-write/references/validate_candidate.py`): the contract forbids
    extra fields, and a top-level-only strip fails on `specification`'s own
    annotation with a confusing error about a field nobody wrote."""
    if isinstance(obj, dict):
        return {k: _strip_annotations(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_annotations(v) for v in obj]
    return obj


def _all_manual(payload: dict[str, Any]) -> bool:
    """Structural read of the stripped payload: True iff `acceptance_criteria`
    is a non-empty list whose every entry declares `verification.kind ==
    "manual"`. Needed because the live contract refuses an all-manual set
    itself (`CandidateWorkItem.at_least_one_executable_criterion`) before the
    C10 branch below could run — the refusal must still name C10."""
    criteria = payload.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria:
        return False
    for criterion in criteria:
        verification = criterion.get("verification") if isinstance(criterion, dict) else None
        if not isinstance(verification, dict) or verification.get("kind") != "manual":
            return False
    return True


def check_understanding(tests: Path) -> GateResult:
    """The Understand node's exit check (T4.3; ExitGateDecision N1 row).

    `tests` is N1's `tests.json` — a `CandidateWorkItem` envelope (ledger
    ruling 2026-09-07). The validator run IS the fresh evidence. In order:
    unreadable/not-JSON/non-object → refused; annotations stripped, then
    validated against the LIVE contract (imported lazily, never vendored) →
    import failure or `ValidationError` refused with its text; zero
    non-`manual` criteria → refused naming C10; zero `WHOLE-PATH:` criteria →
    refused; otherwise ok with one count line. There is NO hold path at N1.
    """
    tests = Path(tests)
    raw = _load_json_object(tests)
    if raw is None:
        return GateResult(ok=False, hold=False, messages=[f"tests file unreadable/not JSON: {tests}"])
    payload = _strip_annotations(raw)

    root = _agentos_root()
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from graph_library.contracts.candidate import CandidateWorkItem  # noqa: PLC0415 — lazy by design
        from pydantic import ValidationError  # noqa: PLC0415
    except Exception as exc:  # a GateResult cannot express exit 2; refuse with the cause
        return GateResult(
            ok=False, hold=False,
            messages=[f"cannot import the live CandidateWorkItem contract from {root}: {exc}"],
        )

    try:
        candidate = CandidateWorkItem(**payload)
    except ValidationError as exc:
        messages: list[str] = []
        if _all_manual(payload):
            messages.append(_C10_REFUSAL)
        messages.append(f"tests.json fails the live CandidateWorkItem contract: {exc}")
        return GateResult(ok=False, hold=False, messages=messages)

    criteria = candidate.acceptance_criteria
    executable = sum(1 for c in criteria if c.verification.kind != "manual")
    if executable == 0:
        # Unreachable while the contract's own all-manual validator stands;
        # kept so the gate does not depend on the contract keeping it.
        return GateResult(ok=False, hold=False, messages=[_C10_REFUSAL])

    whole_path = sum(1 for c in criteria if _WHOLE_PATH_MARKER.match(c.statement))
    if whole_path == 0:
        return GateResult(ok=False, hold=False, messages=[_WHOLE_PATH_REFUSAL])

    return GateResult(
        ok=True, hold=False,
        messages=[f"tests.json valid: {len(criteria)} criteria, {executable} executable, {whole_path} whole-path"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# T4.4 — the Decide node's exit check
# ─────────────────────────────────────────────────────────────────────────────

#: A test id in `mapping.json` is `T<n>`, the 1-based index into the tests
#: file's `acceptance_criteria` (every entry counts, `manual` included —
#: `tests.json` is hash-frozen at N1, so position is stable).
_TEST_ID = re.compile(r"^T[1-9]\d*$")
#: A principle is citable iff the snapshot records it in one of these states.
_CITABLE_STATES = frozenset({"planned", "in-progress", "paused"})
_DEFERRED_HEADING = re.compile(r"^## Deferred\s*$")
_DEFERRED_BULLET = re.compile(r"^\s*[-*]\s+\*\*(.+?)\*\*")
_MAPPING_KEYS = ("tests_file", "deferred_file", "principles_file", "components")


def _resolve_beside(mapping: Path, value: str) -> Path:
    """A `*_file` value resolved relative to the mapping file's own parent
    directory; an absolute value is used as-is (ledger ruling 2026-09-07)."""
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (mapping.resolve().parent / candidate).resolve()


def _deferred_names(text: str) -> set[str]:
    """The bold name of every bullet under a `## Deferred` heading — lines
    after `^## Deferred\\s*$` up to the next `## ` heading or EOF. Other
    sections (`## Kept by principle`, `## Overbloat review`) are ignored."""
    names: set[str] = set()
    inside = False
    for line in text.splitlines():
        if _DEFERRED_HEADING.match(line):
            inside = True
            continue
        if line.startswith("## "):
            inside = False
            continue
        if inside:
            match = _DEFERRED_BULLET.match(line)
            if match:
                names.add(match.group(1))
    return names


def check_deciding(decision: Path) -> GateResult:
    """The Decide node's exit check (T4.4; ExitGateDecision N2 row).

    `decision` is N2's `mapping.json`: every frozen test maps to a named
    component, every component is kept by a test or a declared (citable)
    principle, and anything else is bulleted under `## Deferred` in the
    deferred-list document. Raw JSON and markdown only — no contract
    import, no MCP (the principles snapshot is the demi's job).

    Refusals are staged so the driver fixes a whole stage in one pass:
    mapping unreadable → return; missing keys → all collected, return; the
    three referenced files → all collected, return; then every
    component-level cause and every unmapped test id, all collected.
    There is NO hold path at N2.
    """
    decision = Path(decision)
    mapping = _load_json_object(decision)
    if mapping is None:
        return GateResult(ok=False, hold=False, messages=[f"mapping file unreadable/not JSON: {decision}"])

    messages: list[str] = []
    for key in _MAPPING_KEYS:
        value = mapping.get(key)
        present = isinstance(value, list) if key == "components" else isinstance(value, str) and bool(value)
        if not present:
            messages.append(f"mapping missing key: {key}")
    if messages:
        return GateResult(ok=False, hold=False, messages=messages)

    tests_path = _resolve_beside(decision, mapping["tests_file"])
    principles_path = _resolve_beside(decision, mapping["principles_file"])
    deferred_path = _resolve_beside(decision, mapping["deferred_file"])

    tests_data = _load_json_object(tests_path)
    criteria = tests_data.get("acceptance_criteria") if tests_data is not None else None
    if tests_data is None:
        messages.append(f"tests file unreadable/not JSON: {tests_path}")
    elif not isinstance(criteria, list) or not criteria:
        messages.append(f"tests file declares no acceptance_criteria: {tests_path}")

    principles_data = _load_json_object(principles_path)
    initiatives = principles_data.get("initiatives") if principles_data is not None else None
    if principles_data is None:
        messages.append(f"principles file unreadable/not JSON: {principles_path}")
    elif not isinstance(initiatives, list):
        messages.append(f"principles file declares no initiatives list: {principles_path}")

    deferred: set[str] = set()
    try:
        deferred = _deferred_names(deferred_path.read_text(encoding="utf-8"))
    except OSError:
        messages.append(f"deferred file unreadable: {deferred_path}")
    if messages:
        return GateResult(ok=False, hold=False, messages=messages)

    n_tests = len(criteria)
    states = {
        row["external_id"]: str(row.get("state"))
        for row in initiatives
        if isinstance(row, dict) and isinstance(row.get("external_id"), str)
    }
    components = mapping["components"]
    if not components:
        return GateResult(ok=False, hold=False, messages=["mapping names no components"])

    seen: set[str] = set()
    referenced: set[str] = set()
    kept_by_test = kept_by_principle = deferred_count = 0
    for component in components:
        name = component.get("name") if isinstance(component, dict) else None
        if not isinstance(name, str) or not name:
            messages.append("component has no name")
            continue
        if name in seen:
            messages.append(f"duplicate component name: {name}")
        seen.add(name)

        tests = component.get("tests") or []
        principles = component.get("principles") or []
        if not isinstance(tests, list):
            messages.append(f"{name}: tests must be a list of test ids")
            tests = []
        if not isinstance(principles, list):
            messages.append(f"{name}: principles must be a list of principle ids")
            principles = []

        for test_id in tests:
            test_id = str(test_id)
            if _TEST_ID.match(test_id) and int(test_id[1:]) <= n_tests:
                referenced.add(test_id)
            else:
                messages.append(f"{name}: unknown test id {test_id} (tests.json declares T1..T{n_tests})")
        for principle in principles:
            principle = str(principle)
            state = states.get(principle)
            if state is None:
                messages.append(f"{name}: unknown principle {principle} — not in principles.json")
            elif state not in _CITABLE_STATES:
                messages.append(
                    f"{name}: principle {principle} is {state} — not a declared principle "
                    "(planned/in-progress/paused)"
                )

        if tests:
            kept_by_test += 1
        elif principles:
            kept_by_principle += 1
        elif name in deferred:
            deferred_count += 1
        else:
            messages.append(
                f"{name}: unmapped — no test, no principle, and not named under ## Deferred in {deferred_path}"
            )

    for index in range(1, n_tests + 1):
        if f"T{index}" not in referenced:
            messages.append(f"T{index} maps to no component")

    if messages:
        return GateResult(ok=False, hold=False, messages=messages)
    return GateResult(
        ok=True, hold=False,
        messages=[
            f"mapping valid: {n_tests} tests, {len(components)} components "
            f"({kept_by_test} kept-by-test, {kept_by_principle} kept-by-principle, {deferred_count} deferred)"
        ],
    )


# ─────────────────────────────────────────────────────────────────────────────
# T4.5 — the Draft node's exit check
# ─────────────────────────────────────────────────────────────────────────────

#: A backfilled `task_id` LEADS with a UUID token: the live Plan annotates it
#: — `<uuid> *(backfilled 2026-09-06 from the live row)*` — so only the first
#: whitespace-delimited token (backticks stripped) is matched; the rest is
#: ignored.
_UUID_TOKEN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ZERO_BLOCKS_REFUSAL = "plan declares no task blocks (no level-4 #### T<n>.<m> heading)"
#: A refused non-UUID value is quoted stripped and truncated to this length.
_TASK_ID_PREVIEW = 40


def _strip_task_id(value: str) -> str:
    """Surrounding whitespace and backticks removed — the one normalisation
    the two predicates below and the refusal message share."""
    return value.strip().strip("`").strip()


# Copied from `taskgraph_emit._is_blank_task_id` (system/bin/taskgraph_emit.py L435-437), never imported — that module loads the live contract at import time.
def _is_blank_task_id(value: str) -> bool:
    v = _strip_task_id(value)
    return v == "" or "blank" in v.lower()


def _is_backfilled_task_id(value: str) -> bool:
    tokens = _strip_task_id(value).split()
    return bool(tokens) and _UUID_TOKEN.match(tokens[0].strip("`")) is not None


def check_specifying(plan: Path) -> GateResult:
    """The Draft node's exit check (T4.5; ExitGateDecision N3 row, offline form).

    `plan` is N3's `Plan.md`. Every `#### T<n>.<m>` block must carry a
    non-blank, backfilled `task_id` — the uploader writes them into the Plan
    at filing, so a blank one is a row that was never filed. The Plan is
    read as TEXT through `plan_lint.parse_tasks` (the one task-block parser,
    a sibling module imported lazily): no contract, no MCP, and no lint
    rule — a lint is the plan demi's self-check, not the filing proof.

    In order: plan unreadable → refused; zero task blocks → refused; then
    every per-block cause (no `task_id` marker, blank value, non-UUID value),
    all collected in document order so the driver fixes them in one pass;
    otherwise ok with one count line. There is NO hold path at N3.
    """
    plan = Path(plan)
    try:
        text = plan.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return GateResult(ok=False, hold=False, messages=[f"plan file unreadable: {plan}"])

    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import plan_lint  # noqa: PLC0415 — lazy by design; sibling module, stdlib only

    tasks, _ = plan_lint.parse_tasks(text.splitlines())  # lint violations are the demi's, discarded here
    if not tasks:
        return GateResult(ok=False, hold=False, messages=[_ZERO_BLOCKS_REFUSAL])

    messages: list[str] = []
    for task in tasks:
        field = task.first("task_id")
        if field is None:
            messages.append(f"{task.label}: no task_id field")
            continue
        value = field[0]
        if _is_blank_task_id(value):
            messages.append(f"{task.label}: task_id is blank — not backfilled by the uploader")
        elif not _is_backfilled_task_id(value):
            preview = _strip_task_id(value)[:_TASK_ID_PREVIEW]
            messages.append(f"{task.label}: task_id {preview} is not a UUID — not backfilled by the uploader")

    if messages:
        return GateResult(ok=False, hold=False, messages=messages)
    return GateResult(
        ok=True, hold=False,
        messages=[f"plan valid: {len(tasks)} task blocks, all task_ids backfilled"],
    )


#: Registry, `node -> check callable`, in node order. Step 0 registered
#: `executing`; T4.3 added `understanding`; T4.4 `deciding`; T4.5 adds
#: `specifying` — all four stage nodes now carry a check. T4.8 final
#: closure (2026-09-08): a node absent from this dict is no longer a
#: permissive freeze — `loop_state.py gate-pass` refuses it (exit 2)
#: before ever calling `run_check`, so `CHECKS` is now the closed,
#: complete registry of every node `gate-pass` will accept.
CHECKS: dict[str, Callable[..., GateResult]] = {
    "understanding": check_understanding,
    "deciding": check_deciding,
    "specifying": check_specifying,
    "executing": check_executing,
}


def run_check(node: str, **evidence: Any) -> GateResult | None:
    """Dispatch to `node`'s registered check, or `None` if none is
    registered. T4.8 final closure (2026-09-08): the caller
    (`loop_state.py gate-pass`) now REFUSES an unregistered node (exit 2)
    BEFORE ever calling this function, so a `None` return is unreachable
    from that caller — D6's time-bounded permissive branch ("freeze and
    record without a check") is closed, not merely undocumented. A `None`
    return remains possible only for a caller that dispatches a node
    outside `CHECKS` directly, bypassing `gate-pass`."""
    check = CHECKS.get(node)
    if check is None:
        return None
    return check(**evidence)


__all__ = [
    "DEFAULT_VERIFICATIONS_DIR",
    "GateResult",
    "check_deciding",
    "check_executing",
    "check_specifying",
    "check_understanding",
    "CHECKS",
    "run_check",
]
