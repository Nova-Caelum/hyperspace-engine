---
name: demi-build-tdd
description: Demi-skill of gear5-build. Emits the row's red→green evidence — a failing test observed before code, then the passing run — inside build/<row>/report.md.
disable-model-invocation: true
derives_from: test-driven-development
license: MIT
author: Nova Caelum
version: 1.0
---

# Build — Test First, Evidence in the Report

**Parent node:** `gear5-build`
**Invocable:** No. Reached only by its parent node — embedded in every implementer brief by trigger token, or dispatched with it.
**Emits:** the `## RED` and `## GREEN` sections of `<run-dir>/build/<row>/report.md`

## Overview

Makes a row's change provable before it is claimed: one failing test observed for the right reason, then the smallest change that turns it green, both pasted verbatim into the report. Those two sections are the per-task verification-before-completion evidence the Build node requires before `complete_workitem` (D5).

## Dispatch shape

### Context

- **Anchor docs (READ THESE FIRST):**
  - `<run-dir>/build/<row>/brief.md` — the row's typed acceptance criteria, verbatim
  - the test file each `command_check` criterion names, and the code under change
- **Locked decisions — do NOT re-open:** D5 (VBC per task, before each `complete_workitem`); D8 (explicit test targets — never bare `pytest`, it spawns real inference on this Mac); the row's typed criteria (a repair goes through the controller, never through the test).
- **Loop state:** node `executing`.

### Your task

Turn one row's criteria into a red→green run.

1. Read the typed criteria. For each `command_check` / `file_state`, write one line naming the production change that would make it true — before touching code.
2. **RED.** Write one test for one behavior the row demands: a name that says the behavior, real code under test (mocks only when unavoidable). Run the explicit target. Paste the output under `## RED`. It must FAIL for the expected reason — feature missing, not a typo or import error. Passes immediately → you are testing existing behavior; fix the test. Errors → fix the error, re-run until it fails correctly.
3. **GREEN.** Write the smallest change that passes — no extra options, no neighbour refactors, nothing the test did not ask for. Re-run the same target; paste under `## GREEN`. Any other test in the target red → fix now.
4. Refactor only with green kept; re-run; paste if anything changed.
5. Repeat 2–4 per criterion, then run every explicit target the brief lists once more and paste the summary line.
6. Leave no scratch files; do not commit — promotion is the controller's step on the shared tree.

**Acceptance:** `## RED` shows a failing run for the expected reason; `## GREEN` shows the same target passing; every `command_check` target in the brief is green; no production change exists without a test that failed first.

### Out of scope

- The row's typed criteria, `fixture_schema.json`, any frozen artifact (PRD, Plan, workplan).
- Tests asserting on mocks of the code under test.
- Code written before its test — delete it and implement fresh from the test; do not keep it "as reference".
- `git stash`, `git checkout --`, or any tree-wide revert to stage a "clean" RED — on a shared tree it lifts other implementers' edits. Capture RED by running the target before your change; if you must show the pre-change state later, quote the earlier run.

### Deliverable format

- **Writes:** the code and its test; `## RED` / `## GREEN` in the report — tool output trimmed to the failing/passing lines plus the summary line, never a status word alone.
- **Returns:** nothing beyond the implementer contract in the brief.

### Escalate if

- A criterion cannot be made true by any test-first change (wrong path, wrong target) → return `NEEDS_CONTEXT` naming it; do NOT bend the test to pass.
- The RED run errors for a cause outside the row's files (venv, environment, dependency) → return `BLOCKED` with the output; do NOT install anything inside the vault.
- Green needs a file another in-flight row owns → stop; return the path.

## Self-review

- [ ] For each test: I can name the production change that would make it fail again.
- [ ] `## RED` shows a failure whose message matches the missing feature — not an error.
- [ ] The GREEN diff contains nothing the test did not demand.
- [ ] Every command in the report names explicit test files.
- [ ] No `git stash` / tree-wide revert appears in my commands.

## Gate contribution

`## RED` / `## GREEN` are the node's per-task VBC evidence (D5). Mechanically, closure is discharged by the verifier's `command_check tests` on the row's target; a report without `## RED` is the controller's cue to refuse the report **before** `complete_workitem`, not to discover the gap after.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The work is done; the criteria are a formality the verifier will sort out." | 2026-08-27: seven criteria with `<date>` paths — work finished, hashes recorded, `done` refused. T6.0 (2026-09-06): first closure `unverifiable` on a bare-relative path. Criteria are read and repaired first, through the controller. |
| "Tests written after achieve the same thing." | A test written after passes immediately and proves nothing about its own power to fail. `## RED` exists so "it tests the right thing" has evidence, not faith. |
| "I ran the tests myself; the report's status word is enough." | INC022 Class 1 — *"green status, nothing happened"*, five instances in one night. Pasted output is evidence; a status word is a claim. |

## Source

- **Origin:** T4.2 (2026-09-07); D5 per-task VBC, Daniel-signed 2026-09-07.
- **Precedent failures:** `taskgraph-write` §12 observation 2026-08-27; T6.0 run `4ca9f664` `unverifiable`; INC022 Class 1.
- **Authored by:** chief-pm on 2026-09-07.
- **Community lineage:** obra/superpowers `test-driven-development` 6.3.0 (MIT), archived at `01_research/upstream-source-6.3.0/skills/test-driven-development/SKILL.md`. Ported: iron law; RED → verify → GREEN → verify → refactor; "passes immediately = testing existing behavior". Not ported: TypeScript examples, the graph, `writing-good-tests.md`, ask-your-partner exceptions.
- **Related:** `demi-build-subagent-dispatch`, `verification-before-completion`, `taskgraph-closure`.
