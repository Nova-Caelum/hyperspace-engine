---
name: demi-understand-problem-depth
description: Demi-skill of gear2-understand. Emits 01_understand/Problem.md — the real problem, its stated constraints held hard, and the assumptions register that bounds it.
disable-model-invocation: true
derives_from: brainstorming
license: MIT
author: Nova Caelum
version: 1.0
---

# Understand — Problem Depth

**Parent node:** `gear2-understand`
**Invocable:** No. Reached only by its parent node (step 3), inline or dispatched to a subagent by it.
**Emits:** `<run-dir>/01_understand/Problem.md`

## Overview

Turns a verbatim ask into a one-screen statement of what is actually being solved, for whom, under which stated constraints — with every load-bearing assumption checked before a design exists to rest on it. `demi-understand-test-writing` reads this file to write criteria; `gear3-decide` reads `## Constraints` to check every option against it.

## Dispatch shape

### Context

- **Anchor docs (READ THESE FIRST):**
  - the file passed to `loop_state.py init --input` (`<run-dir>/original_input.md`) — the ask, verbatim; never paraphrased
  - `gear2-understand/references/triage.md` — the path the node already chose at step 1; you record it, you do not re-triage
  - `<run-dir>/loop.state.json` — must read `current_node: understanding`; its `driver` block says who holds the pen (SystemShape §11.8)
  - the assumptions register (step 5) — its own step, never folded into prose (PRD §3.N1)
  - the workspace's frame-discipline rule, Context 2 — requirement → architecture → tool → runbook; stated requirements are HARD from inception
  - source: an internal incident record, 2026-06-21 (INC014: an architecture that failed a stated cloud-independence requirement) — the failure this section order exists to prevent
- **Locked decisions — do NOT re-open:** D5 (N1 exits by validator run; TGC not applicable); the triage call the node made at step 1; the the rulings of 2026-09-07 recorded in a prior run's build ledger: `Problem.md` section names are fixed here and T4.6 renders the template; a spike opens no run — if you are reading this, the path is bounded or architectural.
- **Loop state:** node `understanding`.

### Your task

Write `Problem.md` — seven sections, in this order, these names. Six are yours; the seventh (`## Schema findings`) is appended by `demi-understand-test-writing`.

1. **`## Ask (verbatim)`** — copy the original input, unchanged. Beneath it, restate the goal in ONE sentence. If you cannot after reading the ask and the context it names, stop: return `NEEDS_CONTEXT` naming what is missing. A guess here is the most expensive sentence in the run.
2. **`## Path`** — `bounded | architectural`, one line on why, copied from the node's triage. If what you learn below argues for the heavier path, say so at the top of this section and step up (`triage.md`, the ratchet); never down.
3. **`## Problem`** — the real problem and for whom. Explore before asking: the files the ask names, the run's `notes/` if any, the last worklog entries on the project, recent commits. Then ask — one question per message when the user is present, multiple-choice where the option space is known; purpose, constraints, success criteria. A request that names several independent subsystems is decomposed here into the first sub-goal and a list of the rest; the run proceeds on the first.
4. **`## Constraints`** — every stated requirement, verbatim, each marked `HARD`. Where a thing runs, who can reach it, what it may cost, what it must not depend on — these are constraints, not setup details, whatever the sentence looked like when the user said it. A constraint you can neither satisfy nor test is written down and marked `UNSATISFIABLE — <why>`; it is a stop (below), not a silent drop.
5. **`## Assumptions Register`** — List every assumption the goal rests on (tool behaviour, environment, access, what the existing thing already does), mark each `high | medium | low` confidence and load-bearing yes/no, and verify every low-confidence load-bearing row — documentation first, then a minimal empirical test (one command, one call); reasoning is not verification. Record it as a table: `| Assumption | Confidence | Load-bearing | Verified via | Actual behavior |`. `low confidence + load-bearing` rows are verified before this file is done. A load-bearing row that cannot be verified from this session is a stop.
6. **`## Out of scope`** — what the goal is NOT, and the sub-goals deferred at step 3. Each line is something `gear3-decide` may not add back without a `Problem.md` edit — a double-back the state layer records by hash.
7. Size the file to the path: bounded ≈ one screen (≈40 lines); architectural as long as the constraints need and no longer. Then hand back to the node — its step 4 reads this file and appends `## Schema findings`.

**Acceptance:** the six sections exist in order with these names; the one-sentence restatement is present; every stated requirement appears verbatim under `## Constraints` with ≥1 register row against it; the register is the skill's pasted output, not a table written from memory; nothing under `## Out of scope` also appears under `## Problem`.

### Out of scope

- `tests.json` — owned by `demi-understand-test-writing`.
- Options, sketches, cuts — `gear3-decide`. An option that keeps surfacing while you write `## Problem` becomes one line under `## Out of scope` ("decided at N2"), not a section.
- Re-triaging — the node did it aloud at step 1; you may only step UP, and only by writing why.
- Editing `original_input.md` — the ask is evidence; it is never tidied.

### Deliverable format

- **Writes:** `<run-dir>/01_understand/Problem.md`.
- **Returns (to the node):** the path · constraint count · register rows `verified / unverified` · any stop hit — under 60 words.

### Escalate if

- A stated constraint cannot be satisfied or tested → write it `UNSATISFIABLE`, return to the user with the line; do NOT let `tests.json` be written around it.
- The goal cannot be restated in one sentence → `NEEDS_CONTEXT` naming the missing context; do NOT proceed on the most probable reading.
- A load-bearing register row stays `unverified` → stop; name what would resolve it (access, environment, a ≤20-minute probe); do NOT carry it into `tests.json` as if verified.
- Bounded and architectural both fit and the wrong one is expensive → say so, return to the user; do NOT pick silently.

## Self-review

- [ ] Placeholder scan: no `TBD`, no `<…>`, no "to be confirmed" inside `## Constraints` or the register.
- [ ] Every line under `## Constraints` is a quotation from the ask or from the user in this run — I can point at the source.
- [ ] Every load-bearing register row says HOW it was verified — the doc section or the test and its output — not that it was.
- [ ] Bounded → one screen. Longer means the path is architectural or the file is padded — either is a finding.
- [ ] `## Out of scope` is non-empty. An empty one says the goal has no edge, which is never true.

## Gate contribution

`Problem.md` is one of the two paths frozen by `gate-pass --node understanding --artifact …`. The gate checks that it is NAMED — the registered check refuses an empty `--artifact` list (D6a) — and freezes its hash; **nothing mechanical checks its sections today.** Content is checked twice downstream instead: by the Self-review above at authoring, and by `gear3-decide`, which must check every option against `## Constraints`. The shape is fixed: seven sections, in this order — `## Ask (verbatim)`, `## Path`, `## Problem`, `## Constraints`, `## Assumptions Register`, `## Out of scope`, `## Schema findings` — each with a non-empty body and no unfilled `«FILL: …»` marker; the Self-review checks it, since no gate does (wiring one into the N1 gate would re-open the signed T4.8 table).

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "That's a deployment detail, not a requirement." | An internal incident record (INC014, 2026-06-21): cloud-independence was *"clear in plain language at sprint inception"*, *"treated as a setup detail"*, and the assumption check *"did not run"*. Caught at hour 4, mid-install. Where a thing runs is a constraint; it goes under `## Constraints` verbatim. |
| "I know what they mean; I'll write the problem from the design in my head." | Law 8 (baseline row 4): *"The test was written to describe a design that already existed, instead of the design being written to satisfy a test that already existed."* A problem statement written from the design has the same defect one file earlier. |
| "The assumptions are obvious; I'll list them without running the check." | Test 2/2a (2026-04-21, an internal assumptions-verification record): a docs-sourced conclusion sat in the worklog a day before a 20-minute empirical gate refuted it. The register is verified rows. A table typed from memory is a list of hopes with a column header. |
| "It's a small goal; constraints and a register are overkill." | Then it is bounded and the file is one screen. Baseline row 5: 102 files in an internal catch-all artifacts folder, six of them specs with no constraints section and no tests. Small is a size, not an exemption. |

## Source

- **Parent node:** `gear2-understand`
- **Origin:** Plan T4.3 (2026-08-27); PRD §3.N1 — the assumptions register is its own step, not folded into prose; ruling of 2026-09-07 recorded in a prior run's build ledger: `Problem.md` section names fixed here, template rendered by T4.6.
- **Precedent failures:** an internal baseline record, 2026-09-07 rows 3 (INC014), 4 (Law 8) and 5 (artifacts-folder drift); Test 2/2a docs-refutation precedent (an internal assumptions-verification record, 2026-04-21).
- **Authored by:** the engine's authors on 2026-09-07.
- **Community lineage:** obra/superpowers `brainstorming` 6.3.0 (MIT), archived with the framework's research notes. Ported: explore project context before asking; one question per message, multiple-choice preferred; purpose / constraints / success criteria as the three things to understand; decompose a multi-subsystem request before refining; the one-way ratchet. Not ported: the approaches step (N2), the sectioned design presentation, the design doc under `docs/superpowers/specs/`, the visual companion, the human-approval HARD-GATE (replaced by the validator gate). Port / no-port table: an internal derivation-scope record, 2026-09-07.
- **Sibling demi-skills:** `demi-understand-test-writing`.
