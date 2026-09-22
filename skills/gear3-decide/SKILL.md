---
name: gear3-decide
description: "Use when a run's tests.json is frozen and the design is still open — Daniel says \"what are our options\", \"sketch the architecture\", \"cut this to v1\" — or when a loop run reads current_node: deciding. The second node; after the tests exist, before any PRD or plan."
derives_from: brainstorming
license: MIT
author: Nova Caelum
version: 1.0
---

# gear3-decide — the Decide node (N2)

## Overview

The second stage: generate two or three real options against the frozen tests, sketch the chosen one as named components, and cut every component no test requires — unless cutting it contradicts a principle or initiative we already declared. The Graph Machine PRD designed its whole architecture before its gates existed and shipped a v2-shaped architecture with a v1 label; this framework's own first draft cut artifact hashing because "no criterion fails without it", and Daniel un-cut it because the rule it enforced was a declared principle. This node makes the cut a set operation against a file that already exists, and makes the second half of the rule read a file too.

**Core principle:** A component is in v1 because a frozen test needs it or a live declared principle forbids cutting it — and every other component is named in the deferred document, not remembered.

## The Rule

`set-node … --node deciding` first. Read the frozen `tests.json` and `Problem.md ## Constraints`; walk the three demis in order — options → architecture → descoping; emit `<run-dir>/02_decide/Decision.md`, `Deferred.md`, `mapping.json`, `principles.json`; leave ONLY through `gate-pass --node deciding`, which reads the mapping and refuses any test with no component, any component with neither a test nor a live principle that is not bulleted under `## Deferred`, and any principle that is not in the snapshot or not live. `overbloat-review` is called on the sketch, never folded. Ceremony scales with the path (`Problem.md §Path`); the gate never does.

## When to Use

Fires when:
- `loop.state.json` reads `current_node: understanding` with the N1 gate passed (`Problem.md` + `tests.json` frozen) — the next `set-node` is `deciding`
- Daniel says "what are our options", "sketch the architecture", "cut this to v1", "how do we build this" about a goal whose tests exist
- You are resuming a run at node `deciding` whose `02_decide/mapping.json` is not yet frozen

Does NOT fire for:
- A goal with no frozen `tests.json` → `gear2-understand` first (a spike never reaches here)
- PRD, plan, filing rows → `gear4-draft`; implementing filed rows → `gear5-build`
- Re-opening a frozen criterion — that is a double-back to N1, hash-detected, not a design choice
- A tool or library audit with no goal behind it → `engineering-rigor-compiler` or `overbloat-review` directly

## The Process

1. **Position.** `python3 $AGENTOS_ROOT/system/bin/loop_state.py set-node <run-dir>/loop.state.json --node deciding`. Create `<run-dir>/02_decide/`. Read `01_understand/tests.json` — number its `acceptance_criteria` `T1..TN` in file order; that is the only test vocabulary from here — and `01_understand/Problem.md` (`## Constraints`, `## Out of scope`, `## Path`). Bounded (`§Path`): walk the demis inline, in order. Architectural: each demi MAY be dispatched as a fresh subagent — one at a time, never two in flight.
2. **Options** → `demi/demi-decide-option-generation.md`. Emits `Decision.md ## Options` — two or three approaches, each weighed against every `T<n>` and every `## Constraints` line (satisfies / violates / unknown; an option that violates a HARD constraint is not an option) — and `## Decision`: the one taken, recommendation first, the reason. If Daniel is present, one question: accept or override.
3. **Architecture** → `demi/demi-decide-architecture-sketch.md`. Emits `Decision.md ## Architecture`: the chosen option as named components — for each, what it does, how it is used, what it depends on — plus data flow, error handling, and which `T<n>` each component exists to pass. Names are the mapping's keys: distinctive, stable, reused verbatim downstream.
4. **Descoping** → `demi/demi-decide-ruthless-descoping.md`. Calls `overbloat-review` on `## Architecture` (never folded); writes `principles.json` from `mcp__nova-caelum-ops__list_initiatives` (the check cannot call MCP — the snapshot is how it reads the principles); applies the two-part rule to every component — (a) no `T<n>` needs it AND (b) cutting it contradicts no live initiative — and emits `mapping.json`, `Deferred.md` (`## Deferred` · `## Kept by principle` · `## Overbloat review`), and `Decision.md ## Mapping` + `## Cuts`.
5. **Gate.** File the folder first (`gear2-understand/references/run-folder-schema.md`): everything this node wrote sits where the schema says, nothing new loose at the run root, and each new line in `DRIVE_MAP.md` has its few words. The gate rewrites the map on its way through and prints what is still outside the schema. Then the block below. Exit 0 freezes the four files. `set-node … --node specifying` is `gear4-draft`'s first line, not yours.

## Exit gate
This node exits ONLY through `python3 $AGENTOS_ROOT/system/bin/loop_state.py gate-pass <state> --node deciding --by <you> --artifact <run-dir>/02_decide/Decision.md <run-dir>/02_decide/Deferred.md <run-dir>/02_decide/mapping.json <run-dir>/02_decide/principles.json --decision <run-dir>/02_decide/mapping.json`.
Exit 0 = passed and frozen. 1 = refused (fix the named item, re-run). 2 = evidence unreadable. 3 = HOLD (Build: awaiting Daniel's attestation) — not reachable at N2.
The node's registered check refuses an EMPTY `--artifact` list — a gate that freezes nothing passed nothing (D6a).
verification-before-completion: by construction — the gate computes the evidence; the mapping check IS the fresh evidence, the skill is not separately invoked.
taskgraph-closure: not applicable — no rows exist for this artifact; rows are created at N3.

What `check_deciding` computes (`system/bin/node_gates.py`), from `mapping.json` alone — its `tests_file`, `deferred_file` and `principles_file` are paths relative to its own directory: every `T1..TN` of the frozen tests file is referenced by ≥1 component; every component is kept by a test, kept by a live principle (an `external_id` in `principles.json` whose state is planned, in-progress or paused), or bulleted by exact name under `## Deferred` in `Deferred.md`; no unknown test id, no unknown or dead principle, no duplicate or nameless component. Every refusal of a run is listed at once. `--node deciding` without `--decision` is exit 2.

`$AGENTOS_ROOT` is the canonical `_agentOS` root (this Mac: `$AGENTOS_ROOT`). An edit to any of the four files after exit 0 is a double-back: the state layer detects it by hash.

## The stops

Return to Daniel only for: an option that passes the tests only by violating a HARD constraint (say which line) · a component that (a) cuts and (b) keeps under an initiative, where the keep costs a week rather than a line — the tension is his, not a silent cut (PRD §3.2) · a test no option can pass without a component the constraints forbid — a double-back to N1 he must authorize · a `## Decision` between two options where the wrong one is a rebuild. When `loop.state.json` says he is present, `## Decision` is one question. Everything else is a ruling recorded in `Decision.md`.

## Red Flags

If you catch yourself thinking:
- "No test needs it — cut it" → that is half the rule. PRD §3.2: the first draft cut artifact hashing on exactly that sentence. Read `principles.json` before the cut lands.
- "It's principled, keep it" → name the initiative's `external_id`. If you cannot, it is not a declared principle; the check refuses the id and so should you.
- "I'll sketch the architecture, then map it" → Law 8. Options are weighed against `T<n>` first; components are named per test; the mapping is not decoration on a finished sketch.
- "It's marked v2 in the cut list; the section can stay" → a deferred component leaves `## Architecture`. The `components` list IS the v1 set.
- "This maps to the test we'll write at N3" → there is no such test. An unknown `T<n>` is refused; the honest moves are defer, or a double-back to N1.
- "The Plan names this component, so it exists" → a document's shape is neither a test nor a principle. `overbloat-review`'s `shrink:` tag is exactly this; call it.
- "The architecture obviously satisfies the constraints" → INC014. One line per `## Constraints` entry, per option, before `## Decision`.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "No test needs it — cut it." | PRD §3.2: *"Part (a) said cut, and I cut it."* … *"Cutting the detection leaves the rule intact and unenforceable."* Reversed by Daniel; reversed again on the propagation script (§4). Both halves, every component, with the principle file open. |
| "(b) says it's principled, so keep it." | Daniel, PRD §3.0: *"cheap cut, but measure against the value it loses"* — and *"having a quick fix go off the rails and become sessions of work is a frequent failure mode."* A keep names a live initiative id or it is not a keep; `## Kept by principle` records each one. |
| "I'll sketch the architecture first, then map it to the tests." | Retrospective F2: *"the entire architecture — was designed without the test in view."* Law 8: *"Ruthless cutting requires a criterion to cut against."* Options against `T<n>` first; the sketch names components per test. |
| "It's marked v2 in the cut list; the section can stay." | Retrospective F1: *"a v2-shaped architecture with a v1 label on the gates … The cut happened in the acceptance section and nowhere else."* A deferred component is not in `## Architecture`; the mapping's components ARE v1. |
| "This component maps to the test we'll write at N3." | Law 9: *"No placeholder inside a gate, ever."* Retrospective F3: *"A gate with a placeholder threshold is not a gate."* `T<n>` must exist in the frozen file; the check refuses an unknown id. |
| "The architecture obviously satisfies the constraints." | INC014: the requirement was *"clear in plain language at sprint inception"* and *"treated as a setup detail"*; caught at hour 4. Every option carries one line per `## Constraints` entry. |
| "The Plan names this component, so it exists." | `OverbloatReview_gear2-understand`, 2026-09-07: *"stands as a file because the frozen Plan's T4.3 `Produces` names it — decomposition inherited from the plan, the bloat signature."* Named-by-a-document is unmapped; it goes to `Deferred.md` with that reason. |

## Self-Check

Before claiming the node:
- Did `gate-pass --node deciding` exit 0 — the check's reading of `mapping.json`, not mine?
- Does every option in `## Options` carry a line per `## Constraints` entry, and does `## Decision` say why over the others?
- Is every component in `## Architecture` also a row in `mapping.json`, and is every deferred one absent from `## Architecture` and bulleted under `## Deferred`?
- Does every `## Kept by principle` entry name a live initiative `external_id` and the sentence that says why cutting contradicts it?
- Was `overbloat-review` called on the sketch, and is its output under `## Overbloat review` verbatim?
- Was `overbloat-review` rendered with sufficient context? rejecting a component because a similar one exists is a false reading if the sprint's objective is explicitly to replace those existing components.

## Quick Reference

- **Rule:** `set-node deciding` → options against `T<n>` and `## Constraints` → sketch as named components → two-part cut with the principle snapshot open → exit through the mapping gate.
- **Triggers:** tests frozen, design open; "what are our options" / "sketch the architecture" / "cut this to v1"; `current_node: deciding`.
- **Do:** number the tests once and use only `T<n>`; call `overbloat-review`; write `principles.json` from `list_initiatives`; bullet every deferred component by exact name; freeze all four files.
- **Don't:** cut on (a) alone; keep on a principle you cannot name; map to a test that does not exist; leave a deferred component in `## Architecture`; `set-node specifying` yourself.
- **Escalate to:** Daniel on the stops above; CTO (via Daniel) if `check_deciding` refuses a mapping you can show is correct.

## Out of scope

NOT FOR:
- Problem framing, constraints, test writing → `gear2-understand` (a missing criterion is a double-back, not an N2 fix)
- PRD, plan, filing → `gear4-draft`; rows to `done` → `gear5-build`
- The over-engineering audit itself → `overbloat-review` (called from step 4, never replaced)
- Verifying a tool's behaviour an option rests on → `assumption-check` (call it from step 2 when an option's feasibility is an assumption)

## Source

- **Origin:** Plan T4.4 (2026-08-27; Daniel: the two-part cut rule, PRD §3.0 — *"cheap cut, but measure against the value it loses"*); PRD §3.N2, §3.2 (artifact hashing cut then un-cut), §4 (the v2 cut list as a record); D5 (Daniel-signed 2026-09-07); chief-pm rulings 2026-09-07 in `BUILD_LEDGER.md` (the four `02_decide/` files and their sections; `mapping.json` self-locating with `T<n>` ids; deferred names parsed from `## Deferred`; principles by `external_id`, live states only; exit codes 0/1/2; the freeze set; proportionality; `overbloat-review` placement).
- **Precedent failures:** `m4-loop/gear3-decide-baseline.md` — seven observed rows from four source types: PRD §3.2 + §4 (cut on (a) alone, twice reversed); PRD §3.0 (Daniel's counterweight); retrospective F2 + Law 8 (architecture before the test); retrospective F1 (v2 label, v1 architecture); Law 9 + F3 (placeholder in a gate); INC014 (constraints unchecked); `OverbloatReview_gear2-understand` (plan-inherited file).
- **Authored by:** chief-pm on 2026-09-07.
- **Community lineage:** obra/superpowers `brainstorming` 6.3.0 (MIT), archived at `01_research/upstream-source-6.3.0/skills/brainstorming/SKILL.md`. Ported: propose 2–3 approaches with trade-offs, recommendation first; YAGNI applied to every approach; the design presented by component with what-it-does / how-it-is-used / what-it-depends-on; architecture · components · data flow · error handling · testing as the sketch's coverage. Not ported: the per-section human approval ("ask after each section"), the HARD-GATE before implementation (replaced by the mapping gate and Daniel's `live → done` confirm), the visual companion, the spec file under `docs/superpowers/specs/`, the writing-plans handoff, the process-flow graph. Port / no-port table: `m4-loop/DerivationScope_gear3-decide_ChiefPM_2026-09-07.md`.
- **Related:** `gear2-understand`, `gear4-draft`, `gear5-build`, `overbloat-review`, `assumption-check`, `system/bin/loop_state.py`, `system/bin/node_gates.py`.
