---
name: gear5-build
description: Use when the loop reaches Build — a plan's rows are filed on the Task Graph and must now become working software — or when Daniel says "build it", "execute the plan", "run the rows", or hands you a filed workplan to implement.
derives_from: subagent-driven-development
license: MIT
author: Nova Caelum
version: 1.0
---

# gear5-build — the Build node (N4)

## Overview

The stage that turns filed rows into closed rows. Every prior attempt planned this stage beautifully and never reached it — `make-it-happen`: zero formal invocations, one artifact trail dead at P2; `writing-plans`: zero invocations, its output directory never created. This node is deliberately thin and deliberately the only door: one fresh implementer per row, test first, closure only by the verifier's verdict, exit only through the gate.

**Core principle:** Build progress is a workplan row moving to `done` by verifier verdict on the success of output delivery. Nothing else counts.

## The Rule

Enter through this node or do not build. Per row: brief on disk → fresh implementer → RED→GREEN in the report → `complete_workitem` → verdict read back. Exit only through `gate-pass --node executing`, which reads the verifier's files, never your claim. Rulings, not stalls: decide, ledger the ruling with its cost, keep going — stop only for the four stops below.

## When to Use

Fires when:
- `loop.state.json` reads `current_node: specifying` with the N3 gate passed (rows filed) — the next `set-node` is `executing`
- A workplan JSON names `ready` rows and Daniel says "build it" / "execute the plan" / "run the rows" / "next node"
- You are resuming a run whose `BUILD_LEDGER.md` has rows without a `complete` line

Does NOT fire for:
- Writing or amending the PRD or plan → `gear4-draft`; framing or test authoring → `gear2-understand`; option cuts → `gear3-decide`
- Auditing what was built → CTO, via Daniel
- Build→render→judge visual sprints → `da-vinci`

## The Process

1. **Look around, then position.** `ListAgents` — who else is live and could be in this checkout — and `git fetch && git status -sb` in each repo the run touches; a busy peer or a tree behind `origin` is ledgered before anything is edited. Then `python3 $AGENTOS_ROOT/system/bin/loop_state.py set-node <state> --node executing`. Create or resume `<run-dir>/BUILD_LEDGER.md`; first line `# BUILD ledger — run: <slug> · workplan: <file> · node: executing`. Rows with a `complete` line are done — never re-dispatch them. Read the workplan once; one todo per row.
2. **Conflict scan.** One ledger row per pair of rows sharing a file or interface; one per row for self-consistency (its criteria against its stated files). Rule on every finding before the first dispatch — `Ruling: <what> — <why> — <cost if wrong>`. A clean scan still leaves its table.
3. **Per row — dispatch** (`demi/demi-build-subagent-dispatch.md`; isolation per `demi/demi-build-worktree.md`). Criteria read back and repaired first; brief on disk; model chosen by the row's shape — the least capable that fits (cheapest tier for one or two files with a complete spec, standard for multi-file integration, most capable for design judgment) and always named; one implementer per file set, never two on overlapping files; several same-shape one-line rows batched into ONE brief; ledger line.
4. **Per row — implement** (`demi/demi-build-tdd.md`, carried into the brief by trigger token). RED observed, GREEN observed, both in `build/<row>/report.md`. Handle the return by status — `DONE` → closure; `DONE_WITH_CONCERNS` → resolve correctness/scope concerns first; `NEEDS_CONTEXT` → add it, re-dispatch; `BLOCKED` → change something (context, model tier, split, or a ledgered ruling) before any re-dispatch. A controller fix is allowed only as a D10 mechanical consequence, ledgered.
5. **Per row — close.** Report shows RED and GREEN → `mcp__nova-caelum-verifier__complete_workitem(project, external_id, touched=[…], idempotency_key, proposer_identity, proposer_surface)`. `done` / `already_done` → `Row <id>: complete (run <id>, done)`. `refused` → apply the repair it names, one fix dispatch, one re-close; the same refusal on a discharged criterion is a verifier defect — file it, park the row, no third attempt. `unverifiable` → read what is still outstanding and ledger it. An undischarged `manual` criterion is NOT a deferral: unless the row IS the live test, it is built work Daniel can verify today, and leaving it unclosed is your failure to tell him something was ready for review. Collect these; step 7 is where you walk him through them. Never claim `done` on anything but the verifier's word.
6. **Promote.** Vault repos: `git status` for others' work, then `/git-promote`. Closure does not wait for merge — the verifier reads the working checkout. Deploy is CTO's, after.
7. **Reconcile, then stop.** Before the gate, write `<run-dir>/RECONCILIATION.md` — one markdown bullet per workplan row, in exactly this form:
   ```
   - <external_id> → <done|deferred|archived|live-test>  <free-text: where the work landed>
   ```
   The arrow is `→` (U+2192) and the disposition is one of those four tokens, nothing else. Anything after the token is yours to write and the parser ignores it; headings and prose between bullets are ignored too. **A typo'd token fails closed** — the row reads as missing and the gate refuses, which is the intended direction. Read the dispositions back off the Task Graph; do not write them from memory. Walk it against the PRD, the plan and the component directory: everything that had to be built is built and wired. A component that became two is a pivot and is fine; a row nobody closed because its work *looked* done is the miss this catches. **No new rows here** — an open row is closed, deferred, or archived, and nothing else.
   Then STOP and put it in front of Daniel, with every undischarged `manual` criterion listed by row and quoted. Write `<run-dir>/REVIEW.md` from `references/manual-review-template.md` — per row: the task's name (never an id) · project and module · what was done · what he is checking for · the full path of every file · for code, the exact command, one line or a script file — and put its path in chat, so the word budget binds the chat and not the evidence. A row ready for review that he was never told about is a failure, not a deferral — closed rows are the win, so ask for them.
8. **Exit.** File the folder first (`gear2-understand/references/run-folder-schema.md`): everything this node wrote sits where the schema says, nothing new loose at the run root, and each new line in `DRIVE_MAP.md` has its few words. The gate rewrites the map on its way through and prints what is still outside the schema. Then the gate below. Exit 0 sets `status: live` and leaves `current_node` unchanged: the run is live, Build is over, and the stage that follows is `gear6-live` — announce it there, do not keep building here. Then the finish: collect every `Ruling:` line, in order, each with its cost, under "Rulings I made" — the only place your decisions reach Daniel.

## Exit gate
This node exits ONLY through `python3 $AGENTOS_ROOT/system/bin/loop_state.py gate-pass <state> --node executing --by <you> --artifact <run-dir>/BUILD_LEDGER.md --artifact <run-dir>/RECONCILIATION.md --workplan <workplan.json> --reconciliation <run-dir>/RECONCILIATION.md [--graph-snapshot <snapshot.json>] [--verifications-dir <dir>]`.
Save the snapshot first — `list_work_items` for the project, written to disk verbatim. With it, a `done` row is judged by the graph's `completed_by` (which door closed it: the verifier's committer identity, or Daniel's Caelos console) instead of by whether a verifier run file happens to sit on this Mac. Without it the gate falls back to the original file-scanning behaviour, which cannot tell Daniel's deliberate override from a row nobody closed.
Exit 0 = passed and frozen, and the engine sets `status: live` while leaving `current_node` unchanged — leave the Build node and enter `gear6-live`. 1 = refused: a workplan row is missing from `RECONCILIATION.md`, or declared `done` when the verifier did not close it. Fix the named row; never fix the artifact to match. 2 = evidence unreadable. 3 = HOLD: an undischarged `manual` criterion on a row that is not the live test. The message names each row and quotes its criterion — that list is your agenda with Daniel, not a wait. Write the `REVIEW.md` above for them, close the rows on his word, re-run the gate.
Only a row that IS the live test may cross this gate open, declared `live-test` in the artifact.
The node's registered check refuses an EMPTY `--artifact` list — a gate that freezes nothing passed nothing (D6a).
verification-before-completion: per task, before each complete_workitem — the RED→GREEN run in `build/<row>/report.md`.
taskgraph-closure: the gate — every filed row reads done by verifier verdict.

`$AGENTOS_ROOT` is the canonical `_agentOS` root (this Mac: `$AGENTOS_ROOT`). A ledger edit after exit 0 is a double-back: the ledger is frozen with the gate (D11).

## The four stops

Return to Daniel only for: an irreversible or destructive operation · a security-sensitive action · a side effect outside the workspace that norms say you ask about first (a merge to a shared branch, a publish, an external send) · a plan so broken that every path forward is a guess. Everything else is a ruling.

## Red Flags

If you catch yourself thinking:
- "The brief names a different process" → the brief is stale; the node is not. (This run, 2026-09-07T00:50Z: `mandatory sprint-manager`.)
- "This tooling fix unblocks the row, so it's Build work" → it is not a row. File it through N3's emit or ledger it deferred; the ledger counts rows moved to `done`.
- "I remember where we were" → read the ledger, `loop.state.json`, `git log`. Memory did not survive compaction.
- "The subagent said DONE and the tests pass" → DONE is a report status; `done` is a verifier verdict in `run/verifications/<run_id>.json`.
- "It's six lines, I'll do it inline" → the D10 test: a mechanical consequence of a subagent's own change → patch and disclose; a row's work → dispatch.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The handoff says `sprint-manager` is mandatory, so that's the process." | 2026-09-07T00:50Z, this run: *"Now loading the remaining Step 0 inputs + mandatory `sprint-manager` in one batch."* Daniel: *"That is a retired skill."* An inherited mandate becomes hypothesis when a newer constraint exists (PM-2). |
| "Fixing the verifier / harness / deploy first is the fastest way to the rows." | INC022: six hours, ~2.5M tokens on tracking machinery, **zero** sprint tasks advanced — *"every such loop produces an artifact that looks like progress."* Build's instrument is rows moved to `done`. |
| "Daniel said all of it — parallelize everything." | INC018: *"Green Light"* read as scale authorization; 16 subagents, ~50% of the monthly quota. One implementer per file set; cost card at four. |
| "The work is done; the criteria are a formality." | 2026-08-27: seven `<date>` criteria — hashes recorded, `done` refused. T6.0: `unverifiable` on a bare-relative path until repaired. Read and repair criteria before dispatch. |
| "It's a six-line change; spawning is overhead." | D9 (2026-09-06): inline patch, disclosed after the fact. Allowed only as a D10 mechanical consequence, ledgered with flip cost. |
| "Green status means it happened." | INC022 Class 1 (INC005, INC016, INC019): *"Green status, nothing happened"* — five times in one night. The verifier's run file is the status. |

## Self-Check

Before claiming a row or the node:
- Does the row's report show a RED run that failed for the expected reason, then GREEN on the same target?
- Is the row's `done` a verifier verdict I read back — run id in the ledger — not a subagent's status?
- Is every ruling in the ledger with its cost, and will it reach Daniel under "Rulings I made"?
- Did `gate-pass --node executing` exit 0 with `BUILD_LEDGER.md` in `--artifact`?

## Quick Reference

- **Rule:** the only door from filed rows to `done` — brief → fresh implementer → RED/GREEN → verifier → gate.
- **Triggers:** N3 gate passed; "build it" / "execute the plan" / "run the rows"; a ledger with open rows.
- **Do:** ledger first line, conflict scan, one implementer per file set, model named, verdicts read back.
- **Don't:** re-dispatch completed rows; fix inline outside D10; claim `done` without a verdict; edit the frozen PRD/Plan/workplan (each edit bumps `doubled_back_rounds`).
- **Escalate to:** Daniel on the four stops and for `manual` attestations; CTO (via Daniel) for verifier defects.

## Out of scope

NOT FOR:
- Planning, PRD, plan edits → `gear4-draft`
- Problem framing and test authoring → `gear2-understand`; option generation and cuts → `gear3-decide`
- Auditing shipped work → CTO, via Daniel
- Visually judged frontend sprints → `da-vinci`

## Source

- **Origin:** Plan T4.2 (2026-08-27; Daniel: thin Build node before a polished Draft node); D5 (Daniel-signed 2026-09-07); D11–D13 (2026-09-07).
- **Precedent failures:** `m4-loop/gear5-build-baseline.md` — seven observed rows from four source types: session transcript 2026-09-07T00:50Z; D9; INC022; INC018; `taskgraph-write` 2026-08-27 + T6.0 run `4ca9f664`; INC022 Class 1; upstream re-dispatch after compaction + this run's `fresh_sessions` 2>1.
- **Authored by:** chief-pm on 2026-09-07.
- **Community lineage:** obra/superpowers `subagent-driven-development` 6.3.0 (MIT) — controller shape, ledger, rulings, four stops, report statuses, model selection; archived at `01_research/upstream-source-6.3.0/skills/subagent-driven-development/SKILL.md`. Not ported: reviewer-subagent steps, fix-loop rounds, scripts. Port / no-port table: `m4-loop/DerivationScope_gear5-build_ChiefPM_2026-09-07.md`.
- **Related:** `taskgraph-closure`, `verification-before-completion`, `gear4-draft`, `system/bin/loop_state.py`, `system/bin/node_gates.py`.
