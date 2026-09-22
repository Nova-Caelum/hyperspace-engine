---
name: gear4-draft
description: "Use when a run's decision is frozen and nothing is filed yet — Daniel says \"write the PRD\", \"write the plan\", \"spec it and plan it\", \"file the rows\" — or when a loop run reads current_node: specifying. The third node; after the design is decided, before anything is built."
derives_from: writing-plans
license: MIT
author: Nova Caelum
version: 1.0
---

# gear4-draft — the Draft node (N3)

## Overview

The third stage: render the frozen decision into a specification and a plan, then file the plan's rows — and exit only when every task block in the plan carries the identifier the Task Graph handed back. Two stalls shaped this node. The planning skill this one adapts sat in a persona's loadout with zero invocations, ever, and its mandated output directory was never created; a plan that never becomes tracked work is indistinguishable from a plan nobody wrote. And the uploader's first real run located 0 of 45 identifier fields, printed PASS, and backfilled nothing — so the gate here reads the document, not the exit code.

**Core principle:** A plan is tracked work or it is not a plan. The node exits when the Plan on disk carries a backfilled `task_id` in every task block, checked by a script that reads the Plan.

## The Rule

`set-node … --node specifying` first. Read the four frozen N2 files and the two frozen N1 files; walk the three demis in order — PRD → Plan → emit; emit runs `taskgraph_emit.py validate`, `plan`, `apply`, and `apply` writes the identifiers back into the Plan; leave ONLY through `gate-pass --node specifying`, which reads the Plan and refuses any `####` task block whose `task_id` is blank or not a UUID. The gate runs AFTER the backfill, so the frozen bytes are the complete ones. Each writing demi carries its own self-review and fixes inline; there is no reviewer subagent — not in the node, not in the demis. Ceremony scales with the path (`Problem.md §Path`); the gate never does.

## When to Use

Fires when:
- `loop.state.json` reads `current_node: deciding` with the N2 gate passed (`02_decide/` four files frozen) — the next `set-node` is `specifying`
- Daniel says "write the PRD", "write the plan", "spec it and plan it", "file the rows", "get it onto the graph" about a goal whose decision exists
- You are resuming a run at node `specifying` whose `03_draft/Plan.md` is not yet frozen

Does NOT fire for:
- A goal with no frozen `mapping.json` → `gear3-decide` first (and `gear2-understand` before that if no `tests.json`)
- Implementing filed rows → `gear5-build`
- Editing a frozen PRD or Plan after the gate — that is a double-back, hash-detected, not a draft
- A single Task Graph row with no run behind it → `taskgraph-placement` + `taskgraph-write` directly

## The Process

1. **Position.** `python3 $AGENTOS_ROOT/system/bin/loop_state.py set-node <run-dir>/loop.state.json --node specifying`. Create `<run-dir>/03_draft/`. Read `02_decide/Decision.md`, `Deferred.md`, `mapping.json`, `principles.json` and `01_understand/Problem.md`, `tests.json` — number the tests `T1..TN` in file order exactly as N2 did; the mapping's `components` list IS the v1 set. Bounded (`§Path`): walk the demis inline, in order. Architectural: each demi MAY be dispatched as a fresh subagent — one at a time, never two in flight.
2. **Specification** → `demi/demi-draft-prd-writing.md`. Emits `03_draft/PRD.md` with its eight fixed sections: the acceptance set verbatim from `tests.json`; one page of what is being built; `## Components` rendered FROM `mapping.json` (no component the mapping lacks — a new one is a double-back to N2); `## Principles` naming each cited initiative with its Task Graph entry; `## v2 recap` — the deferred components, plain, no reasoning; decisions inherited; what v1 does not claim; and `## Closeout — rules enforced only by prose`. Self-review inside the demi, fixed inline.
3. **Plan** → `demi/demi-draft-plan-writing.md`. Emits `03_draft/Plan.md` in the task-block format the uploader parses: `##` modules, `####` tasks, all eleven field markers per task, `Summary` in plain English, `Produces` naming every created file by its decided path, `task_id` left EMPTY, `plan_lint` CLEAN before hand-back, and every `## Acceptance set` entry served by at least one task's `Serves`.
4. **Emit** → `demi/demi-draft-taskgraph-emit.md`. Review the Plan against the PRD (every acceptance entry on ≥1 task), map it to `03_draft/workplan.json`, then `python3 $AGENTOS_ROOT/system/bin/taskgraph_emit.py validate <workplan>`, `plan <workplan>`, `apply <workplan>`. `apply` exit 0 files every row, reads each one back, and writes the generated identifiers into the Plan's `task_id` fields. Exit 1 → fix the workplan or the Plan and re-run; exit 2 → infrastructure, report it; exit 3 → partial, re-run `apply`. **Never file a row by hand** — filing around a refusal is the bypass this node exists to close.
5. **Gate.** File the folder first (`gear2-understand/references/run-folder-schema.md`): everything this node wrote sits where the schema says, nothing new loose at the run root, and each new line in `DRIVE_MAP.md` has its few words. The gate rewrites the map on its way through and prints what is still outside the schema. Then the block below. Exit 0 freezes the three files. `set-node … --node executing` is `gear5-build`'s first line, not yours.

## Exit gate
This node exits ONLY through `python3 $AGENTOS_ROOT/system/bin/loop_state.py gate-pass <state> --node specifying --by <you> --artifact <run-dir>/03_draft/PRD.md <run-dir>/03_draft/Plan.md <run-dir>/03_draft/workplan.json --plan <run-dir>/03_draft/Plan.md`.
Exit 0 = passed and frozen. 1 = refused (fix the named item, re-run). 2 = evidence unreadable. 3 = HOLD (Build: awaiting Daniel's attestation) — not reachable at N3.
The node's registered check refuses an EMPTY `--artifact` list — a gate that freezes nothing passed nothing (D6a).
verification-before-completion: by construction — the gate computes the evidence; `taskgraph_emit.py apply` reads every filed row back and the check reads the identifiers it wrote into the Plan, the skill is not separately invoked.
taskgraph-closure: not applicable — this node creates rows; it closes none.

What `check_specifying` computes (`system/bin/node_gates.py`), from the Plan alone: every level-4 `#### T<n>.<m>` task block — found by `plan_lint`'s parser, the same one the lint uses — carries a `task_id` field whose value is non-blank and begins with a UUID; a Plan with no task blocks is refused; every refusal of a run is listed at once. `--node specifying` without `--plan` is exit 2. `apply` exiting 0 is the precondition, not the proof: the emitter's first real run printed PASS with nothing backfilled, which is why the gate reads the document. The order is draft → emit → backfill → gate → freeze; a backfill after exit 0 modifies a frozen artifact and the state layer counts it as a double-back.

`$AGENTOS_ROOT` is the canonical `_agentOS` root (this Mac: `$AGENTOS_ROOT`). An edit to any of the three files after exit 0 is a double-back: the state layer detects it by hash.

## The stops

Return to Daniel only for: an acceptance-set entry no task can serve — a plan gap that is a design gap, so a double-back to N2 he must authorize · the emitter refuses and you believe the refusal is wrong — say so, never route around it (a gate you can talk yourself past is not a gate) · `apply` exit 2 — auth or transport, not yours · a task whose honest budget exceeds his per-task caps — say so in its `Budget` field; the overrun options are his: defer, promote to module, abandon · when `loop.state.json` says he is present, one question at the end of step 2: accept the v1 set as rendered, or override — never a re-design. Everything else is a ruling recorded in the PRD's `## Decisions inherited`.

## Red Flags

If you catch yourself thinking:
- "The emitter exited 0, so the rows are in" → 2026-08-27: 0 of 45 fields located, PASS printed, nothing backfilled. The gate reads the Plan, and so should you.
- "Freeze the plan first so nothing changes it, then file" → the backfill writes into the plan. Gate after backfill, or the double-back counter fires on our own tooling (Plan L61).
- "The plan is written; we'll file the rows when we start building" → a plan that never becomes tracked work is a plan nobody wrote. `gear5-build` has no door without rows.
- "The task is obvious from the plan's flow; the fields are padding" → Daniel: *"not even vaguely stand alone."* Eleven fields, every block; `Summary` readable with no other document open.
- "The PRD is where the architecture gets written properly" → a v2-shaped architecture with a v1 label (retrospective F1). `## Components` comes from `mapping.json`; a new component is a double-back to N2.
- "The deferred list is in `Deferred.md`; the PRD needn't repeat it" → that context is exactly what gets lost (Daniel, PRD L511). `## v2 recap`, plain, no reasoning.
- "It validated, so the criterion files" → seven `<date>` criteria filed, work finished, `done` refused. A criterion can be false today and names the change that makes it true.
- "The rows are obvious — `upsert_work_item` is one call each" → filing by hand is the universal bypass. The script writes; you review and map.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The emitter exited 0, so the identifiers are in the plan." | `taskgraph_emit.py` L447–456: *"located 0 of 45 fields on the first real plan this gate was ever run against … The gate printed PASS and backfilled nothing."* `check_specifying` reads every `####` block's `task_id`; the exit code is not the evidence. |
| "The task is obvious from the plan's flow." | Plan L40: the first draft *"fails to provide enough context to be considered even vaguely stand alone"* — it *"dropped Context on every task in favour of density."* Daniel's rule (L42): *"maximizing durable context, minimizing what gets lost in a session context."* |
| "The implementer will name the file; the plan says what it makes." | Plan L56: *"A task whose output is 'the thing it makes' is not plannable by an agent that cannot see this conversation."* `Produces` names every file by its decided path. |
| "The plan is written; we'll file when we start building." | PRD §3.3: *"`superpowers:writing-plans` has zero invocations ever, and its mandated output directory does not exist anywhere in the vault. A plan that never becomes tracked work is indistinguishable from a plan nobody wrote."* Filing is the exit. |
| "Freeze the plan first so nothing changes it." | Plan L61: *"the emitter would modify a frozen artifact and the fix-versus-pivot counter would fire on its own tooling."* L63: *"draft → emit → backfill → gate passes → freeze."* |
| "The deferred list is in `Deferred.md`; the principles are on the graph." | PRD L511 (Daniel): *"a recap of what needs / will be built in v2. No why. … Alot of that context gets lost and i want to fix that."* L155: the principles section *"listing the relevant initiatives and pointing to the taskgraph copy of it."* L61: *"a closeout doc … this maybe prose enforced in which case we may have to harden."* Three sections, required. |
| "The PRD is where the architecture gets written properly." | Retrospective F1: *"a v2-shaped architecture with a v1 label on the gates … The cut happened in the acceptance section and nowhere else."* `## Components` is the mapping, rendered. |
| "It validated, so the criterion files." | `taskgraph-write` L127: *"seven filed criteria carried `<date>` … The contract had accepted all seven: it checks a path is repo-relative, never that it is achievable."* The plan is where a criterion is made honest; the emitter carries it verbatim. |

## Self-Check

Before claiming the node:
- Did `gate-pass --node specifying` exit 0 AFTER `apply` exited 0 — the check's reading of the backfilled Plan, not mine?
- Does every `####` block carry all eleven fields, a plain `Summary`, a `Produces` naming each created file by path, and a criterion that can be false today?
- Is every `## Acceptance set` entry served by ≥1 task's `Serves`, and does `## Components` name nothing `mapping.json` lacks?
- Do `## Principles`, `## v2 recap` and `## Closeout — rules enforced only by prose` carry content, not headings?
- Was every self-review item run inside its demi and fixed inline — no second pass, no reviewer subagent?

## Quick Reference

- **Rule:** `set-node specifying` → PRD from the frozen mapping → Plan in the task-block format, `task_id` empty → emit (`validate`, `plan`, `apply`; `apply` backfills) → exit through the plan gate.
- **Triggers:** decision frozen, nothing filed; "write the PRD" / "write the plan" / "file the rows"; `current_node: specifying`.
- **Do:** render components from `mapping.json`; three Daniel sections in the PRD; eleven fields per task; `plan_lint` CLEAN; every acceptance entry served; gate after backfill; freeze all three files.
- **Don't:** add a component at N3; file a row by hand; gate before `apply`; edit a frozen PRD/Plan; dispatch a reviewer; `set-node executing` yourself.
- **Escalate to:** Daniel on the stops above; CTO (via Daniel) if `check_specifying` refuses a Plan you can show is fully backfilled, or the emitter refuses a workplan you can show is valid.

## Out of scope

NOT FOR:
- Problem framing and test writing → `gear2-understand`; options, architecture, cuts → `gear3-decide` (a missing component is a double-back, not an N3 addition)
- Rows to `done` → `gear5-build`
- A Task Graph row outside a run → `taskgraph-placement` + `taskgraph-write`
- The uploader's mechanics → `demi/demi-draft-taskgraph-emit.md` and `system/bin/taskgraph_emit.py` (called from step 4, never re-described here)

## Source

- **Origin:** Plan T4.5 (2026-08-27; Daniel: *"taskgraph emit should be the end of the draft node … We do not build if there's no guide in the task graph"*; the three PRD-template items; checklist form mirrored from upstream; no reviewer subagent); PRD §3.3; D5 (Daniel-signed 2026-09-07); chief-pm rulings 2026-09-07/08 in `BUILD_LEDGER.md` (offline form of the check; `03_draft/` artifacts and freeze set; PRD section names; the closeout as a section; `verifying` as the remaining unregistered node; `derives_from`).
- **Precedent failures:** `m4-loop/gear4-draft-baseline.md` — eight observed rows from six source types: `taskgraph_emit.py` L447–456 (PASS, nothing backfilled); Plan L40/L42/L56 (Daniel review: stand-alone context, `Produces` by path); Plan L61/L63 (backfill-before-gate order); PRD §3.3 L186 (zero invocations); PRD Daniel notes L155/L511/L61 (the three sections); retrospective F1 (v2-shaped spec); `taskgraph-write` L127 (`<date>` criteria).
- **Authored by:** chief-pm on 2026-09-07.
- **Community lineage:** obra/superpowers `writing-plans` 6.3.0 (MIT), archived at `01_research/upstream-source-6.3.0/skills/writing-plans/SKILL.md`. Ported: the Self-Review as a checklist the author runs — *"not a subagent dispatch"* — with the fix-inline-no-re-review clause; the No Placeholders list as plan failures; File Structure before tasks (a `Path` per task, decomposition locked in the plan); Task Right-Sizing (a task is the smallest unit that carries its own criterion); the Scope Check (one goal per plan — a plan that needs decomposition is a finding, not two plans); a header that carries the spec pointer and the global constraints. Not ported: the Execution Handoff offer (`gear5-build` is the only door), the `docs/superpowers/plans/` path, the `REQUIRED SUB-SKILL` header line, bite-sized 2–5-minute code-block steps (our tasks are rows sized to Daniel's caps and implemented by `gear5-build`'s fresh implementer), `plan-document-reviewer-prompt.md`, the announce-at-start line. Port / no-port table: `m4-loop/DerivationScope_gear4-draft_ChiefPM_2026-09-07.md`.
- **Related:** `gear2-understand`, `gear3-decide`, `gear5-build`, `taskgraph-write`, `taskgraph-placement`, `system/bin/taskgraph_emit.py`, `system/bin/plan_lint.py`, `system/bin/loop_state.py`, `system/bin/node_gates.py`.
