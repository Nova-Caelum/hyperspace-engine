---
name: demi-understand-test-writing
description: Demi-skill of gear2-understand. Emits 01_understand/tests.json — the acceptance criteria that define done, validated against the live contract before any design.
disable-model-invocation: true
derives_from: taskgraph-write
license: MIT
author: Nova Caelum
version: 1.0
---

# Understand — Test Writing

**Parent node:** `gear2-understand`
**Invocable:** No. Reached only by its parent node (step 4), inline or dispatched to a subagent by it.
**Emits:** `<run-dir>/01_understand/tests.json` · the `## Schema findings` section of `<run-dir>/01_understand/Problem.md`

## Overview

Writes the file that defines finished before anything is designed: typed acceptance criteria in the `CandidateWorkItem` envelope, every one dischargeable today, at least one executable, at least one walking the whole path from entry to terminal effect. The node's exit gate reads this file and nothing else; N2 cuts scope against it; N3 files it; the verifier at N4 discharges it.

## Dispatch shape

### Context

- **Anchor docs (READ THESE FIRST):**
  - `<run-dir>/01_understand/Problem.md` — `## Problem`, `## Constraints`, `## Out of scope`; every criterion traces to one of these
  - `_agentOS/skills_library/taskgraph-write/SKILL.md` §12 and `references/candidate-template.json` — copy the template; never compose the envelope from memory
  - `_agentOS/skills_library/taskgraph-write/references/validate_candidate.py` — the pre-gate validator (exit 0 `VALID` · 1 `INVALID` with field-addressed reasons · 2 contract unavailable)
  - `_agentOS/graph_library/contracts/candidate.py` — the live contract the gate imports: verification kinds, `no_traversal`, `SUPPORTED_TOKENS`, the all-manual refusal
  - `AgentSecretBase/workspace/hyperspace-engine_new_sprintframework/01_understand/tests.json` — a real N1 output (predates the `WHOLE-PATH:` marker; read, never edit) and `Tests_ChiefPM_2026-08-27.md` §"Where the schema fought us" — the five known limits of the contract
  - `02_loop-design/SystemShape_LoopIntegration_ChiefPM_2026-08-27.md` §11.9 — why one criterion must walk the whole path
- **Locked decisions — do NOT re-open:** D5 (N1's gate is the validator run); C10; the chief-pm rulings of 2026-09-07 (`BUILD_LEDGER.md`): `tests.json` keeps the `CandidateWorkItem` envelope; the whole-path criterion is a `statement` beginning `WHOLE-PATH:`; `understanding` exit codes 0 / 1 / 2, no HOLD.
- **Loop state:** node `understanding`; `Problem.md` exists.

### Your task

Produce a validated `tests.json` from `Problem.md`.

1. **Trace.** For each line under `## Constraints` and each outcome under `## Problem`, decide: one criterion, several, or none-expressible. "None-expressible" is legal only with an `uncertainty_notes` entry (step 5). Each criterion's `statement` names an observable outcome and implies the change that would make it true today — if it is true already, it is not a criterion.
2. **Envelope.** Copy `candidate-template.json` to `<run-dir>/01_understand/tests.json`; fill it truthfully and minimally: `project` = the goal's project code, `external_id` = `<project>:<goal-slug>-acceptance`, `module: null`, `specification` from `Problem.md` (`problem` ≥40 chars, `why_it_matters` ≥40, `context_pointer` = the `Problem.md` path), ≥1 `source_references` (the ask, `Problem.md`). `type` and placement are a claim you are NOT making at N1 — record one `uncertainty_notes` entry, kind `wrong-type`, detail "envelope placement is provisional; N3 decides", check "`taskgraph-placement` at N3". Strip every `_`-prefixed key, at every depth.
3. **Criteria, 1–20, typed.** `command_check` (`check_id` ∈ tests · typecheck · build · lint · git_diff_nonempty; `target` vault-relative WITH the repo prefix — `_agentOS/system/…`, `AgentSecretBase/…` — resolved from `$VAULT_ROOT/`, the verifier's evidence root; no shell metacharacters) · `file_state` (`path` vault-relative the same way — no `..`, no leading `/` or `~`; `assertion` ∈ exists · not_exists · contains · hash_equals · modified_after · glob_exists — `exists` only on a path ABSENT today, otherwise `contains` / `modified_after` / `hash_equals`) · `manual` (`instruction` ≥10 chars; only for what only Daniel can attest — it binds at Build, not here). Never `db_readback` / `http_readback`: no allowlist registry exists, so an unknown id fails as `uncertain`, quietly. Keep the manual criteria and ADD an executable one beside each — the contract refuses an all-manual set before the gate does.
4. **The whole-path criterion.** At least one `statement` begins `WHOLE-PATH:` — that literal, uppercase, colon, first thing in the string. Shape: `WHOLE-PATH: <the entry action> → <the terminal observable effect>` — the criterion that FAILS when any component between them is disconnected. Prefer a non-`manual` verification (a `command_check tests` target that drives the path end to end; a `file_state contains` on the terminal artifact). Unit tests on components never satisfy it; the GM proposal gate had those and shipped unwired.
5. **What the schema refuses, report — never soften.** Runtime paths (`~/.claude/…`), absolute paths, a registry lookup, an outcome no kind expresses: the outcome goes into `uncertainty_notes` (kind `unverified-claim`; `detail` = the outcome and which rule refused it; `check` = how a human or tool would verify it) AND one line under `## Schema findings` in `Problem.md` (append the section; write `none` if nothing was refused). A criterion is never rewritten to the nearest thing that validates. `<…>` appears in a `path` or `target` only as one of the four filing tokens (`<date>`, `<run-id>`, `<slug>`, `<project>`), and only where the value is genuinely unknowable until N3 files it. `uncertainty_notes` is a required key that may be an empty list — empty means "nothing I doubt"; an absent key is silence, a different answer (never omit it).
6. **Validate.** `python3 $AGENTOS_ROOT/skills_library/taskgraph-write/references/validate_candidate.py <run-dir>/01_understand/tests.json`. Fix every field it names; re-run until `VALID`. Exit 2 is a stop (below).
7. Hand back to the node for `gate-pass --node understanding`. Do not run `gate-pass` yourself; never `set-node`.

**Acceptance:** `validate_candidate.py` prints `VALID`; ≥1 criterion is non-`manual`; ≥1 `statement` begins `WHOLE-PATH:`; every `## Constraints` line traces to a criterion or an `uncertainty_notes` entry; no `exists` on a present path; no `<…>` outside the four filing tokens; `## Schema findings` exists in `Problem.md`.

### Out of scope

- Swapping an outcome the contract cannot express for an easier one that validates — the refusal is reported (step 5); the criterion is not weakened.
- `Problem.md` beyond appending `## Schema findings` — owned by `demi-understand-problem-depth`.
- The contract, the template, `validate_candidate.py`, `node_gates.py` — read, never edited; a contract that cannot say a real outcome is a finding for CTO via Daniel.
- The gate and `set-node` — the node's, after you return.

### Deliverable format

- **Writes:** `<run-dir>/01_understand/tests.json`; the `## Schema findings` section of `Problem.md`.
- **Returns (to the node):** the path · the validator's `VALID` line verbatim · `N criteria, E executable, W whole-path` · schema findings count — under 80 words.

### Escalate if

- A `## Constraints` line has no expressible criterion AND no `uncertainty_notes` entry can name a check → return to Daniel naming the line; do NOT file a criterion that does not test it.
- `validate_candidate.py` exits 2 (contract unavailable) → `BLOCKED` with the stderr; do NOT vendor a copy of the contract or hand-validate.
- The only whole-path criterion you can write is `manual` → write it `manual`, add the nearest executable proxy beside it, say so in the return; do NOT drop the `WHOLE-PATH:` prefix to make the set look tidier.
- A criterion is already true today and you cannot name a change that would make it false → the outcome is not this goal's; hand it to the node for `## Out of scope`; do NOT keep it as padding.

## Self-review

- [ ] Ambiguity: for every criterion I can name the change that makes it true today and the change that would make it fail again; no `statement` admits two readings.
- [ ] No `<` / `>` in any `path` or `target` except the four filing tokens, each where the value is unknowable until N3.
- [ ] No `exists` on a path that is present now; no `not_exists` on one that is absent now.
- [ ] The `WHOLE-PATH:` criterion fails if any single component between entry and terminal effect is disconnected — not only if one is broken.
- [ ] Internal consistency: every `## Constraints` line is traced; no two criteria contradict each other; every schema refusal is in `uncertainty_notes` AND `## Schema findings`; no criterion was softened to avoid one.
- [ ] Placeholder scan: `specification` carries nothing the contract's `is_placeholder` refuses; no `statement` carries anything a reader would call one.
- [ ] Scope: the criteria fit one goal — a set that needs decomposition goes back to the node (`demi-understand-problem-depth` step 3), not into one `tests.json`.

## Gate contribution

Direct and total: `tests.json` IS what `check_understanding` (`system/bin/node_gates.py`) reads at `gate-pass --node understanding --tests <path>` — parses; validates as `CandidateWorkItem` against the live contract; ≥1 non-`manual`; ≥1 `WHOLE-PATH:`. Exit 0 freezes it. **Unchecked by the gate:** whether each criterion could actually fail today — the contract's already-true lint (`lint_already_true_file_state`) runs only at admission with an evidence root, not at N1. The Self-review carries that check; it is a finding, and the observed cost of missing it is seven `<date>` criteria refused at `finalize` (2026-08-27).

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Every component has its own tests, so the thing is tested." | SystemShape §11.9: *"the GM worker's unit tests would have passed fine while it sat unwired."* The proposal gate shipped that way. One `WHOLE-PATH:` criterion, and the gate refuses its absence. |
| "This criterion can't be met as written — I'll write one that can." | Graph Machine retrospective: *"That substitution is how P5 came to be marked done while the attempt node still ran a mock."* The unmeetable outcome is recorded — `uncertainty_notes`, `## Schema findings` — never swapped. |
| "The schema can't say it, so I'll write the nearest thing that validates." | The framework's own tests set: *"Reported honestly rather than fudged … this is the most valuable thing to return."* Five schema limits reported as findings; none smoothed into a weaker criterion. |
| "It validated, so it's a test." | `taskgraph-write` §12, observed 2026-08-27: *"seven filed criteria carried `<date>` … The contract had accepted all seven: it checks a path is repo-relative, never that it is achievable."* `VALID` is the floor. Each criterion names the change that would make it fail today. |
| "I'll write the tests once the design is clear enough to test against." | Law 8: the gates sat at *"position 1,342 of 1,528 lines"*; *"ruthless cutting requires a criterion to cut against."* This file is N1's exit; `deciding` cannot open without it. |

## Source

- **Parent node:** `gear2-understand`
- **Origin:** Plan T4.3 (2026-08-27); PRD §1 C10, §3.N1; SystemShape §11.9 (whole-path constraint); D5 (Daniel-signed 2026-09-07); chief-pm rulings 2026-09-07 in `BUILD_LEDGER.md` (envelope kept; `WHOLE-PATH:` marker; exit codes).
- **Precedent failures:** `m4-loop/gear2-understand-baseline.md` rows 1, 2, 4, 6, 7 — worker unwired; P5 mock; Law 8; the schema findings of the framework's own tests set; the seven `<date>` criteria.
- **Authored by:** chief-pm on 2026-09-07.
- **Lineage:** internal — `_agentOS/skills_library/taskgraph-write/SKILL.md` §12 (the proposal surface: copy the template, run the validator, the two refused shapes — `<` / `>` in a path and `exists` on a present path —, `uncertainty_notes` as the honest channel, keep the manual criteria and add an executable one). Not ported: the 11-item pre-flight (placement, duplicate scan, effort, state, description ceiling), Rule Zero, the post-write fresh-read — those bind at N3's emit, not here. Secondary, from obra/superpowers `brainstorming` 6.3.0 (MIT, archived at `01_research/upstream-source-6.3.0/skills/brainstorming/SKILL.md`): the spec self-review's four checks (placeholder · consistency · scope · ambiguity) applied to criteria; "success criteria" as the third thing to understand. Port / no-port table: `m4-loop/DerivationScope_gear2-understand_ChiefPM_2026-09-07.md`.
- **Sibling demi-skills:** `demi-understand-problem-depth`.
