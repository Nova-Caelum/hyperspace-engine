---
name: demi-build-subagent-dispatch
description: Demi-skill of gear5-build. Emits build/<row>/brief.md — the on-disk brief a fresh implementer subagent is dispatched with — and the ledger line that records it.
disable-model-invocation: true
derives_from: subagent-driven-development
license: MIT
author: Nova Caelum
version: 1.0
---

# Build — Dispatch a Fresh Implementer

**Parent node:** `gear5-build`
**Invocable:** No. Reached only by its parent node.
**Emits:** `<run-dir>/build/<row>/brief.md` (on disk before the `Agent` call) · `Row <id>: dispatched …` in `BUILD_LEDGER.md` · `<run-dir>/build/<row>/report.md`, written by the controller from the report the implementer returns

## Overview

Turns one workplan row into one dispatch: a brief on disk that is the implementer's only source of requirements, a fresh subagent with its model named, and a ledger line. The controller's context stays clean for rulings; the implementer's context holds exactly one task.

## Dispatch shape

### Context

- **Anchor docs (READ THESE FIRST):**
  - `gear5-build/references/handoff-prompt-template.md` — the brief's shape; copy it
  - the row: `get_work_item(external_id)`; typed criteria via its `acceptance_criteria_ref`, or from the workplan JSON when `get_graph_run` returns 403
  - `<run-dir>/BUILD_LEDGER.md` — in-flight rows and their file ownership
  - the row's `Isolation:` ruling (`demi/demi-build-worktree.md`)
- **Locked decisions — do NOT re-open:** D10 (mechanical-consequence edits: the implementer makes and discloses them); D11–D13; chief-pm delta 1 (≥4 subagents in one batch → cost card, HALT for Daniel).
- **Loop state:** node `executing`.

### Your task

Dispatch one row.

1. Read back the row's typed criteria. Any criterion that cannot discharge as written — a `<placeholder>` in a path, `exists` on a path already present, a `command_check` target that is not vault-relative WITH the repo prefix (`_agentOS/…`, `AgentSecretBase/…` — the verifier resolves `target` from the vault root, never from a repo cwd) — is repaired FIRST through the sync update door (`upsert_work_item … update_acceptance_criteria: true`) and confirmed with `get_work_item`. Only then continue.
2. Record `BASE=$(git rev-parse HEAD)` in the repository the row touches; write it into the brief.
3. Write `<run-dir>/build/<row>/brief.md` from the template: anchor docs, locked decisions, the `Isolation:` line, trigger tokens (`TDD`, `verification-before-completion`), the criteria verbatim, other in-flight rows' files as out of scope, the report format (returned as the implementer's final message — never a file; the harness refuses subagent report files), the return cap (it binds the status line, not the report body), the escalation table. Exact values appear in the brief and nowhere else.
4. Choose the model by the row: one or two files with a complete spec → cheapest tier; multi-file integration → standard; design judgment → most capable. Name it in the `Agent` call — an omitted model inherits the controller's.
5. Dispatch ONE implementer: `Agent(subagent_type=<row's assignee_agent>, model=<named>, isolation="worktree" only when the ruling says so)`. The message is a pointer — one line on where the row fits, the brief path introduced as "read this first — it is your requirements", interfaces from earlier rows the brief cannot know, the instruction to return the report as the final message. No pasted history. Never two implementers on overlapping files; several same-shape one-line rows go into ONE brief.
6. Append `Row <id>: dispatched (brief <path>, model <m>, base <sha7>)` to the ledger. Keep working — next brief, ledger, reading reports; never poll.
7. Handle the return by status. FIRST, before any other tool call, write the returned report verbatim to `<run-dir>/build/<row>/report.md` — a return that is not on disk is lost, and a missing report reads exactly like a missing agent. `DONE` → read the report's `## RED`/`## GREEN`, hand to the node's closure step. `DONE_WITH_CONCERNS` → correctness or scope concerns are resolved before closure; observations are ledgered. `NEEDS_CONTEXT` → add the missing context to the brief, re-dispatch. `BLOCKED` → change something — context, model tier, a split, or a ledgered ruling on a plan defect — before any re-dispatch. Never the same dispatch twice.

**Acceptance:** brief on disk before the `Agent` call; model named; one implementer per file set; ledger line present; the controller has written the report file before its next tool call.

### Out of scope

- Fixing the implementer's findings in the controller session — re-dispatch with the findings. Exception, disclosed: a D10 mechanical consequence, ledgered as a `Ruling:` with flip cost.
- Reviewer subagents (task reviewer, re-reviewer, final reviewer) — the verifier's `complete_workitem` and CTO's audit are the review layer; a worker-spawned reviewer is a duplicate seat.
- Closing the row — the node's closure step owns `complete_workitem`.

### Deliverable format

- **Writes:** the brief; the ledger line.
- **Returns (to the node):** brief path, the dispatch's agent identity, `BASE` — under 40 words.

### Escalate if

- The batch would reach four subagents → print the cost card and HALT for Daniel (INC018); do NOT dispatch the fourth.
- The criteria cannot be repaired without changing what the row means → `Ruling:` in the ledger, return to the controller; do NOT dispatch against a criterion that cannot discharge.
- The implementer returns `BLOCKED` twice on the same cause → ledger a plan defect; do NOT dispatch that row again.

## Self-review

- [ ] The brief's file timestamp precedes the `Agent` call.
- [ ] The model is named in the call.
- [ ] Every exact value (path, name, string) is in the brief and not in the dispatch message.
- [ ] The ledger line names brief path, model, base.

## Gate contribution

Indirect, load-bearing: the report file this dispatch's controller writes is where `demi-build-tdd`'s RED/GREEN evidence lands, and the node refuses `complete_workitem` on a row whose report lacks it. The gate itself (`gate-pass --node executing`) reads only verifier files.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It's six lines; dispatching is overhead." | D9 (2026-09-06): chief-pm patched inline because `SendMessage` was disabled — disclosed after the fact. Six lines with a brief costs minutes; six lines without a report trail costs the review. D10 bounds the exception: mechanical consequence, disclosed, ledgered. |
| "Daniel said all of it — fire every row in parallel." | INC018: *"Green Light"* read as scale authorization; 16 subagents, ~50% of the monthly quota. One implementer per file set; cost card at four. |
| "I'll describe the task in the prompt; the brief is a formality." | Upstream observed a 42k-character dispatch that was 99% pasted history. The brief on disk is what a re-dispatched implementer reads; the prompt is gone. |

## Source

- **Origin:** T4.2 (2026-09-07); PRD §N4 row — "Dispatch via the existing handoff template + AP-2".
- **Precedent failures:** D9 inline patch; INC018 quota blowout; sprint-manager AP-2 (spawn without a saved prompt).
- **Authored by:** chief-pm on 2026-09-07.
- **Community lineage:** obra/superpowers `subagent-driven-development` 6.3.0 (MIT), archived at `01_research/upstream-source-6.3.0/skills/subagent-driven-development/SKILL.md`. Ported: brief on disk, report file, four statuses, no-subagents contract, BASE, model selection, batch same-shape work, never parallel on shared files. Not ported: reviewer prompts, review packages, fix-loop rounds, implementer question round-trips.
- **Related:** `demi-build-tdd`, `demi-build-worktree`, `references/handoff-prompt-template.md`.
