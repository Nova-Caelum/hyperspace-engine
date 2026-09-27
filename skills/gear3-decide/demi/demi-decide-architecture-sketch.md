---
name: demi-decide-architecture-sketch
description: Demi-skill of gear3-decide. Emits 02_decide/Decision.md §Architecture — the chosen option as named components, each with its purpose, interface and dependencies.
disable-model-invocation: true
derives_from: brainstorming
license: MIT
author: Nova Caelum
version: 1.0
---

# Decide — Architecture Sketch

**Parent node:** `gear3-decide`
**Invocable:** No. Reached only by its parent node (step 3), inline or dispatched to a subagent by it.
**Emits:** `<run-dir>/02_decide/Decision.md` — `## Architecture` (appended after `## Decision`)

## Overview

Decomposes the chosen option into named components a stranger could build and test independently — each with what it does, how it is used, what it depends on, and which `T<n>` it exists to pass. The names written here are the keys of `mapping.json`; `demi-decide-ruthless-descoping` cuts against this list and `gear4-draft` plans from it.

## Dispatch shape

### Context

- **Anchor docs (READ THESE FIRST):**
  - `<run-dir>/02_decide/Decision.md` — `## Options` (the `T<n>` list and the per-test lines of the chosen option) and `## Decision`; you sketch that option and no other
  - `<run-dir>/01_understand/tests.json` — the frozen criteria; the `WHOLE-PATH:` criterion is the one your data flow must walk end to end
  - `<run-dir>/01_understand/Problem.md` — `## Constraints` (every component honours every line), `## Out of scope` (nothing here comes back as a component)
  - `skills/gear5-build/demi/demi-build-subagent-dispatch.md` — the shape N4 dispatches from; a component a fresh implementer cannot brief from your four lines is under-specified
- **Locked decisions — do NOT re-open:** the `## Decision` (a better option found mid-sketch is a return to the node, not a silent switch); the frozen `tests.json`; the the rulings of 2026-09-07 recorded in a prior run's build ledger: component names are the mapping keys — distinctive, stable, reused verbatim by the descoping demi and by N3.
- **Loop state:** node `deciding`; `Decision.md` exists with `## Options` + `## Decision`.

### Your task

Append `## Architecture` to `Decision.md`.

1. **Name the components.** One `### <component name>` per unit — a name a grep finds (`parity test file`, not `the test`), stable for the rest of the run. A unit has one clear purpose; if you cannot say its purpose in one sentence, split it; if two units share a purpose, merge them.
2. **Four labelled lines per component:** **Does** — what it does; **Used by** — its interface: who calls it and how (a CLI flag, a function, a file it writes, a section it fills); **Depends on** — the components, files, tools or services it needs; **Passes** — the `T<n>` ids this component exists to pass, or `none` (write `none` honestly; the descoping demi decides what `none` means, you do not).
3. **Data flow.** One `### Data flow` paragraph or ordered list from entry to terminal effect — the path the `WHOLE-PATH:` criterion walks — naming each component in order. A component that appears in no step of the flow is a finding: say so beside it.
4. **Error handling and testing.** `### Error handling` — what fails loudly, what holds the run, what never fails open (PRD §3.3: a gate that lets the run through on error is the advisory kill loop again). `### Testing` — for each `T<n>`, which component's test discharges it and where that test lives (a `command_check` target path, a `file_state` path).
5. **Isolation check.** For every component, answer: can someone understand it without reading its internals? can the internals change without breaking its callers? If either is no, the boundary moves before this file is handed back. Keep the sketch proportional to `Problem.md §Path`: bounded ≈ one screen; architectural as long as the components need and no longer.
6. Hand back to the node for step 4. Do not write `## Mapping`, `## Cuts`, `mapping.json` or `Deferred.md`.

**Acceptance:** every component has a unique `###` name and the four labelled lines; `### Data flow` names every component or flags the ones it does not; `### Testing` covers every `T<n>`; nothing under `Problem.md ## Out of scope` appears as a component; the sketch is the `## Decision` option and no other.

### Out of scope

- Choosing or changing the option — `demi-decide-option-generation`; a switch mid-sketch returns to the node.
- Cutting components or judging (a)/(b) — `demi-decide-ruthless-descoping`. Write `Passes: none` and move on; the cut is the next demi's set operation, not your intuition.
- `## Mapping`, `## Cuts`, `mapping.json`, `principles.json`, `Deferred.md` — the descoping demi's files.
- Implementation detail below the interface (function bodies, schemas beyond the fields a caller sees) — N3 plans it, N4 builds it.

### Deliverable format

- **Writes:** `<run-dir>/02_decide/Decision.md` — the `## Architecture` section only.
- **Returns (to the node):** the path · component count · the count with `Passes: none` · any component absent from the data flow · any boundary you moved — under 60 words.

### Escalate if

- The chosen option cannot walk the `WHOLE-PATH:` criterion end to end without a component `## Out of scope` forbids → return to the node naming both; do NOT add the component quietly.
- A component's `Depends on` names a tool or service whose behaviour nobody has verified and `## Decision` carries no register row for it → return to the node for an assumptions-register row (docs, then a minimal test); do NOT sketch on the assumption.
- The sketch only works if the option changes → return to the node; do NOT rewrite `## Decision`.

## Self-review

- [ ] Every `###` name is unique, grep-able, and I would recognise it in `mapping.json` a week from now.
- [ ] No component's `Does` line needs "and" to join two purposes.
- [ ] `### Data flow` walks the `WHOLE-PATH:` criterion; the component that discharges it is named in `### Testing`.
- [ ] Placeholder scan: no `TBD`, no component whose `Used by` is "various", no `Passes` line left blank (`none` is a value; blank is not).

## Gate contribution

Indirect but load-bearing: the `###` names are the `name` values of `mapping.json`'s components, and `check_deciding` refuses a duplicate or nameless component and matches deferred names by exact string against `Deferred.md`. A name changed between this section and the mapping is an unmapped component at the gate. The Self-review carries what no lint can see; for the file's SHAPE, `Decision.md` carries `## Options`, `## Decision`, `## Architecture`, `## Mapping`, `## Cuts`, in that order, each non-empty with no unfilled `«FILL: …»` marker — checked by the Self-review, deliberately not by `check_deciding`.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "One component per criterion — the tests give me the decomposition." | The overbloat review's `shrink:` tag: *"Structure that reflects how an artifact was built rather than what it does"* — three validation helpers because the spec had three bullets. Components come from the problem's shape; `Passes` lists which tests each one serves, often several. |
| "I'll leave the components vague; the plan will firm them up." | N4 dispatches a fresh implementer per row from a brief; a component that cannot be briefed from its four lines is re-designed at Build, in the most expensive context. Retrospective F1: the v2-shaped architecture arrives exactly when nobody committed to units. |
| "Every component has its own test, so testing is covered." | SystemShape §11.9 (`gear2-understand` baseline row 1): unit tests passed while the worker sat unwired. `### Data flow` walks the `WHOLE-PATH:` criterion and `### Testing` names the component whose test fails when the path breaks. |

## Source

- **Parent node:** `gear3-decide`
- **Origin:** Plan T4.4 (2026-08-27); PRD §3.N2; rulings of 2026-09-07 recorded in a prior run's build ledger: `Decision.md ## Architecture` fixed; component names are the mapping keys.
- **Precedent failures:** an internal baseline record, 2026-09-07 rows 3 (architecture before the test), 4 (v2 label on v1 sections), 7 (plan-inherited decomposition); an internal baseline record, 2026-09-07 row 1 (worker unwired).
- **Authored by:** the engine's authors on 2026-09-07.
- **Community lineage:** obra/superpowers `brainstorming` 6.3.0 (MIT), archived with the framework's research notes §"Presenting the design" and §"Design for isolation and clarity". Ported: cover architecture · components · data flow · error handling · testing; scale each section to its complexity; break the system into units with one clear purpose and well-defined interfaces; per unit — what it does, how you use it, what it depends on; the two boundary questions (understand without internals / change internals without breaking consumers); follow existing patterns in an existing codebase. Not ported: "ask after each section whether it looks right" (no per-section human approval — the gate is the mapping check), the visual companion, the design-doc write and its user-review gate. Port / no-port table: an internal derivation-scope record, 2026-09-07.
- **Sibling demi-skills:** `demi-decide-option-generation`, `demi-decide-ruthless-descoping`.
