---
name: gear2-understand
description: Use when a goal arrives unframed — Daniel says "let's figure out what we're building", "spec this out", "what does done look like", "is this worth doing" — or when a loop run opens with no tests file for its goal. The first node; before any design, plan or build starts.
derives_from: brainstorming
license: MIT
author: Nova Caelum
version: 1.0
---

# gear2-understand — the Understand node (N1)

## Overview

The first stage: find the real problem, hold the stated constraints hard, and write the tests that define finished — before anything is designed. The Graph Machine PRD wrote its acceptance gates at line 1,342 of 1,528, so the architecture was designed without the test in view and a stage was marked done against a mock. Its proposal gate then shipped with the worker unwired, because every component had unit tests and nothing exercised the path. This node exists so the cut at N2 is a set operation against a file that already exists, and so one criterion in that file walks the whole path.

**Core principle:** Nothing is designed until a validated `tests.json` says what finished means — and at least one of its criteria exercises the whole path.

## The Rule

Triage first (`references/triage.md`): spike, bounded or architectural — said out loud. A **spike** opens no run and writes nothing; it ends in chat with an answer. **Bounded** and **architectural** open a run, emit `<run-dir>/01_understand/Problem.md` and `<run-dir>/01_understand/tests.json`, and leave ONLY through `gate-pass --node understanding`, which validates the tests file against the live `AcceptanceCriterion` contract and refuses an all-manual set or a set with no whole-path criterion. Ceremony scales with the path; the gate never does.

## When to Use

Fires when:
- A goal arrives that nobody has framed — a new feature, subsystem, tool, or "should we"; Daniel says "let's figure out what we're building", "spec this out", "what does done look like", "is this worth doing"
- No `loop.state.json` exists for the goal, or it reads `current_node: framing`
- You are resuming a run at node `understanding` whose `01_understand/tests.json` is not yet frozen

Does NOT fire for:
- Option generation, architecture sketch, scope cuts → `gear3-decide`
- PRD, plan, filing rows → `gear4-draft`; implementing filed rows → `gear5-build`
- A failing thing whose problem is already known — that is debugging, not understanding
- A spike's follow-up ("the probe worked, keep it") — that is a new request; classify it again

## The Process

1. **Triage.** Read `references/triage.md`. Classify the request and say the classification before the first question. Spike → step 2s. Bounded or architectural → step 2. When in doubt, the heavier path; hidden complexity found later upgrades the path — stop, say so, step up. Nothing downgrades mid-run.
2. **Open the run.** `<parent-dir>` is `AgentSecretBase/workspace` — a run nested deeper never appears in the SessionStart banner. Write the verbatim ask to `<parent-dir>/<slug>/original_input.md` first (`init` hashes the text into the state file and does not copy it — the file the demis anchor on exists only if you wrote it), then `python3 $AGENTOS_ROOT/system/bin/loop_state.py init --goal <slug> --input <parent-dir>/<slug>/original_input.md --workspace <parent-dir>`, then `set-node <run-dir>/loop.state.json --node understanding`. The state file is the goal's registration — a run that dies here still counts. `init` also lays down the run-folder skeleton (`handoffs/`, `notes/`, `misc/`) and the first `DRIVE_MAP.md`; from this line on, every file goes where `references/run-folder-schema.md` says. Create `<run-dir>/01_understand/`.
   - **2s. Spike.** No `init`, no files, no gate. Present the question and what you will try in two or three sentences; if Daniel is present, get a nod. Find out as cheaply as correctness allows. Report a recommendation. Anything you built is labelled throwaway.
3. **Problem depth** → `demi/demi-understand-problem-depth.md`, inline or dispatched. Emits `Problem.md`: the verbatim ask, the path and why, the real problem and for whom, `## Constraints` (every stated requirement, HARD from inception), `## Assumptions Register` produced by calling `assumption-check` — never folded — and what is out of scope. Bounded: one screen.
4. **Test writing** → `demi/demi-understand-test-writing.md`. Emits `tests.json` in the `CandidateWorkItem` envelope: every criterion typed and dischargeable today; at least one with `verification.kind` other than `manual`; at least one whose `statement` begins `WHOLE-PATH:`. What the schema refuses to express goes into `uncertainty_notes` and a `Problem.md` line — never into a softened criterion.
5. **File the folder.** Read `references/run-folder-schema.md`. Move everything this node wrote to its place — nothing loose at the run root beyond the schema's own list. `python3 $AGENTOS_ROOT/system/bin/drive_map.py write <run-dir>`, then give each new line under **Full map** its few words after the dash. `set-node` and `gate-pass` rewrite the map themselves — entry and exit of every node — so it is never stale at a gate; what they cannot do is file your loose files or describe them.
6. **Validate before the gate.** `python3 $AGENTOS_ROOT/skills_library/taskgraph-write/references/validate_candidate.py <run-dir>/01_understand/tests.json` — fix what it names; then the gate below. Exit 0 freezes both files. `set-node … --node deciding` is `gear3-decide`'s first line, not yours.

## Exit gate
This node exits ONLY through `python3 $AGENTOS_ROOT/system/bin/loop_state.py gate-pass <state> --node understanding --by <you> --artifact <run-dir>/01_understand/Problem.md <run-dir>/01_understand/tests.json --tests <run-dir>/01_understand/tests.json`.
Exit 0 = passed and frozen. 1 = refused (fix the named item, re-run). 2 = evidence unreadable. 3 = HOLD (Build: awaiting Daniel's attestation) — not reachable at N1.
The node's registered check refuses an EMPTY `--artifact` list — a gate that freezes nothing passed nothing (D6a).
verification-before-completion: by construction — the gate computes the evidence; the validator run IS the fresh evidence, the skill is not separately invoked.
taskgraph-closure: not applicable — no rows exist for this artifact; rows are created at N3.

What `check_understanding` computes (`system/bin/node_gates.py`): the tests file parses; it validates as a `CandidateWorkItem` against the live contract in `graph_library/contracts/candidate.py`; ≥1 criterion is machine-checkable (C10); ≥1 criterion's statement begins `WHOLE-PATH:` (C10/C12 — the criterion that would have caught the proposal gate). `--node understanding` without `--tests` is exit 2. A spike never opened a run and has nothing to gate; its exit is the recommendation in chat.

`$AGENTOS_ROOT` is the canonical `_agentOS` root (this Mac: `$AGENTOS_ROOT`). A `Problem.md` or `tests.json` edit after exit 0 is a double-back: the state layer detects it by hash.

## The stops

Return to Daniel only for: a stated constraint you can neither satisfy nor test (say which) · a goal you cannot restate in one sentence after reading its context (`NEEDS_CONTEXT`, not a guess) · a triage call where bounded and architectural both fit and the wrong one is expensive · a criterion only he can attest (write it `manual`; it binds at Build, not here). When `loop.state.json` says he is present, questions are cheap — one at a time, answer before the next. Everything else is a ruling recorded in `Problem.md`.

## Red Flags

If you catch yourself thinking:
- "I know what he means; the tests would just restate the design" → Law 8: the design shrinks by construction only when the tests exist first. Write them.
- "This one is small; the node is overkill" → then it is a spike or bounded. The spike costs nothing. Skipping the node is how `_artifacts/` filled with specs nobody gated.
- "I'll call it a spike" → reaching for the label to skip the gate IS the doubt. Take the heavier path.
- "Every component has tests" → the worker's unit tests passed while it sat unwired. Where is the `WHOLE-PATH:` criterion?
- "That's a deployment detail" → INC014. A stated requirement is a constraint; it goes in `## Constraints` verbatim and N2 checks every option against it.
- "The schema can't say it, so the nearest thing that validates" → report it in `uncertainty_notes`; never a weaker criterion.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Every component has its own tests, so the thing is tested." | SystemShape §11.9: *"the GM worker's unit tests would have passed fine while it sat unwired"* — the proposal gate shipped that way. One `WHOLE-PATH:` criterion is required, and the gate refuses its absence. |
| "This criterion can't be met as written — I'll write one that can." | Graph Machine retrospective: *"That substitution is how P5 came to be marked done while the attempt node still ran a mock."* An unmeetable outcome is recorded NOT MET with its reason, never swapped. |
| "That's a deployment detail, not a requirement." | INC014: cloud-independence was *"clear in plain language at sprint inception"* and *"treated as a setup detail"*; the assumption check *"did not run"*; caught at hour 4, mid-install. Constraints are written down and `assumption-check` is called. |
| "I'll write the tests once the design is clear enough to test against." | Law 8: the gates sat at *"position 1,342 of 1,528 lines"* and *"ruthless cutting requires a criterion to cut against."* `tests.json` is this node's exit artifact; `deciding` cannot open without it. |
| "This one's small; the node is overkill — I'll just write the spec." | PRD §3.1(b) predicted *"ad-hoc specs landing in `_artifacts/`"*; observed 2026-09-07: 102 files there, six of them PRDs, plans and specs with no tests file. The spike path costs nothing — use it, or use bounded. |
| "The schema can't say it, so I'll write the nearest thing that validates." | The framework's own tests set: *"Reported honestly rather than fudged … this is the most valuable thing to return."* Four schema constraints were reported as findings, none smoothed into a weaker criterion. |
| "It validated, so it's a test." | 2026-08-27: *"seven filed criteria carried `<date>` … The contract had accepted all seven: it checks a path is repo-relative, never that it is achievable."* Validation is the floor; each criterion names the change that would make it fail today. |

## Self-Check

Before claiming the node:
- Did I say the path out loud, and does the ceremony match it — a spike wrote nothing, a run has both files?
- Does `DRIVE_MAP.md` show nothing under **Outside the schema** that I put there?
- Did `gate-pass --node understanding` exit 0 — not my reading of the file, the gate's?
- Is every stated requirement in `## Constraints` verbatim, with an assumption-check row against it?
- Could every criterion fail today, and can I name the change that would make each true?
- Did the schema refuse anything — and is it in `uncertainty_notes` rather than smoothed over?

## Quick Reference

- **Rule:** triage aloud → spike answers in chat, writes nothing; bounded/architectural open a run, emit `Problem.md` + `tests.json`, exit through the validator gate.
- **Triggers:** an unframed goal; "spec this out" / "what does done look like"; no state file or `current_node: framing`.
- **Do:** constraints verbatim and HARD; `assumption-check` called; ≥1 executable criterion; ≥1 `WHOLE-PATH:` criterion; report what the schema refused.
- **Don't:** write tests after the design; swap an unmeetable criterion for an easier one; call it a spike to skip the gate; `set-node deciding` yourself.
- **Escalate to:** Daniel on the stops above; CTO (via Daniel) if the contract itself cannot express a real outcome.

## Out of scope

NOT FOR:
- Options, architecture, cuts → `gear3-decide`
- PRD, plan, filing → `gear4-draft`; rows to `done` → `gear5-build`
- Verifying a tool's behaviour before a design rests on it → `assumption-check` (called from step 3, not replaced)
- Debugging a known failure → out of scope; the problem is not unknown

## Source

- **Origin:** Plan T4.3 (2026-08-27; Daniel: "the cheap path must be genuinely cheap"); PRD §3.N1, §3.1(b), C10; D5 (Daniel-signed 2026-09-07); SystemShape §11.9 whole-path constraint; chief-pm rulings 2026-09-07 in `BUILD_LEDGER.md` (envelope, `WHOLE-PATH:` marker, exit codes, spike opens no run).
- **Precedent failures:** `m4-loop/gear2-understand-baseline.md` — seven observed rows from six source types: SystemShape §11.9 + ProcessNotes L519 (worker unwired); Graph Machine retrospective (P5 mock); INC014; Law 8; PRD §3.1(b) + `_artifacts/` listing; the framework's own tests set (schema findings); `taskgraph-write` §12 (`<date>` criteria).
- **Authored by:** chief-pm on 2026-09-07.
- **Community lineage:** obra/superpowers `brainstorming` 6.3.0 (MIT), archived at `01_research/upstream-source-6.3.0/skills/brainstorming/SKILL.md`. Ported: three-path classification said aloud; one-way ratchet; "too simple to need approval" as "too simple to need tests"; explore context first; Red Flags table shape. Not ported: the HARD-GATE human approval before implementation (replaced by the validator gate and Daniel's `live → done` confirm), the visual companion, the spec file under `docs/superpowers/specs/`, the process-flow graph, the writing-plans handoff. Port / no-port table: `m4-loop/DerivationScope_gear2-understand_ChiefPM_2026-09-07.md`.
- **Related:** `gear3-decide`, `gear4-draft`, `gear5-build`, `assumption-check`, `taskgraph-write` (contract references), `system/bin/loop_state.py`, `system/bin/node_gates.py`.
