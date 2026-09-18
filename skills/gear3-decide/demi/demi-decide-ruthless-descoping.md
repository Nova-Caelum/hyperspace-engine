---
name: demi-decide-ruthless-descoping
description: Demi-skill of gear3-decide. Emits 02_decide/mapping.json, principles.json and Deferred.md — the two-part cut applied to every component against frozen tests and declared principles.
disable-model-invocation: true
derives_from: none
license: MIT
author: Nova Caelum
version: 1.0
---

# Decide — Ruthless Descoping

**Parent node:** `gear3-decide`
**Invocable:** No. Reached only by its parent node (step 4), inline or dispatched to a subagent by it.
**Emits:** `<run-dir>/02_decide/mapping.json` · `<run-dir>/02_decide/principles.json` · `<run-dir>/02_decide/Deferred.md` · the `## Mapping` and `## Cuts` sections of `<run-dir>/02_decide/Decision.md`

## Overview

Applies Daniel's two-part cut rule to every component in `## Architecture`: a component is cut to v2 when **(a)** no frozen test needs it **and (b)** cutting it contradicts no principle we have declared — the principles being initiatives on the Task Graph, snapshotted to a file so the gate can read them. The output is the machine-readable mapping `check_deciding` judges, the deferred document the rule requires, and the snapshot that makes (b) a lookup instead of a feeling.

## Dispatch shape

### Context

- **Anchor docs (READ THESE FIRST):**
  - `<run-dir>/02_decide/Decision.md` — `## Architecture` (the `###` component names and their `Passes` lines) and `## Options` (the `T<n>` list)
  - `<run-dir>/01_understand/tests.json` — the frozen criteria; `T<n>` = 1-based position in `acceptance_criteria`, every entry, `manual` included
  - `AgentSecretBase/workspace/hyperspace-engine_new_sprintframework/PRD_NovaCaelumFramework_ChiefPM_2026-08-27.md` §3.0 (the two-part rule, Daniel's words), §3.2 (artifact hashing: cut on (a), un-cut on (b)), §4 (the v2 cut list as a record)
  - `_agentOS/skills_library/overbloat-review/SKILL.md` — called at step 2, never folded; its five tags are cut evidence, its output is advisory
  - `_agentOS/system/bin/node_gates.py` `check_deciding` — what the gate reads; the shapes below are what it accepts
- **Locked decisions — do NOT re-open:** the frozen `tests.json` (a test you wish existed is a double-back to N1); `## Decision` and the component names in `## Architecture` (a rename returns to the node); the chief-pm rulings of 2026-09-07 (`BUILD_LEDGER.md`): file names, the `mapping.json` shape, `T<n>` by position, principles by `external_id` in live states only, deferred names parsed from `## Deferred` as bold-led bullets, the freeze set.
- **Loop state:** node `deciding`; `Decision.md` has `## Options`, `## Decision`, `## Architecture`.

### Your task

Write the three files and the two sections, in this order.

1. **Snapshot the principles.** Call `mcp__nova-caelum-ops__list_initiatives` and write `principles.json`: `{"captured_at": "<ISO-8601 UTC>", "source": "mcp__nova-caelum-ops__list_initiatives", "initiatives": [{"id", "external_id", "title", "state"} …]}` — the FULL return projected to those four fields, no filtering (the check filters by state; the file is a faithful snapshot). A principle is citable iff its `state` is `planned`, `in-progress` or `paused`. If the call fails, stop (below): the second half of the rule cannot run on memory.
2. **Call `overbloat-review`** on `Decision.md ## Architecture` (the artifact is the component list). Paste its full output verbatim under `Deferred.md ## Overbloat review`. Its `shrink:` / `yagni:` / `redundant:` / `native:` / `dormant-risk:` tags are inputs to step 3 — a component the review names is examined first; the review never cuts anything by itself.
3. **Apply (a) to every component.** For each `###` name in `## Architecture`, list the `T<n>` ids it is needed to pass — not the ids it helps with, the ids that FAIL if it is deleted. Cross-check against `## Options`' per-test lines and `## Architecture`'s `Passes` lines; where they disagree, the delete-test wins. A component with a non-empty list is **kept by test**.
4. **Apply (b) to the rest.** For each component with an empty (a) list: does cutting it contradict a citable initiative in `principles.json`? Name the `external_id` and write ONE sentence saying what the principle commits us to and why the cut breaks it (PRD §3.2 is the worked example — the fix-vs-pivot rule needs hashing to bind). A sentence that names no `external_id` keeps nothing. A component with ≥1 such initiative is **kept by principle**; record it under `Deferred.md ## Kept by principle` as `- **<name>** — `<external_id>`: <the sentence>`.
5. **Defer the rest.** Every component with empty (a) and empty (b) is **deferred**: bullet it under `Deferred.md ## Deferred` as `- **<exact component name>** — (a) no test: checked T1..TN; (b) principles: none contradicted (snapshot <captured_at>); reopen when: <the test or principle that would pull it back>`. The bold text must equal the component name byte-for-byte — the check matches strings. A deferred component is REMOVED from `## Architecture` (replace its `###` block with one line `### <name> — deferred → Deferred.md`); it stays in `mapping.json` with empty lists so the gate can see it was judged.
6. **Write `mapping.json`.** `{"run": "<slug>", "tests_file": "../01_understand/tests.json", "deferred_file": "Deferred.md", "principles_file": "principles.json", "components": [{"name": "<###>", "tests": ["T<n>", …], "principles": ["<external_id>", …]}, …]}` — paths relative to the mapping file's own directory; one entry per `###` in `## Architecture` including the deferred ones; names unique, byte-equal to the headings. Then check: every `T1..TN` appears in ≥1 component's `tests` — a test no kept component passes means the sketch is short a component (return to the node) or the test is unmeetable (a stop).
7. **Write `## Mapping` and `## Cuts` in `Decision.md`.** `## Mapping`: a table — Component · Tests · Principles · Status (`kept-by-test` / `kept-by-principle` / `deferred`) — mirroring `mapping.json` row for row. `## Cuts`: the deferred count and the kept-by-principle count, `see Deferred.md`, and the `overbloat-review` score line verbatim. Hand back to the node for the gate. Do not run `gate-pass` yourself; never `set-node`.

**Acceptance:** `principles.json` is the full `list_initiatives` return with `captured_at`; `Deferred.md` has all three sections (`## Deferred` may carry no bullets; `## Overbloat review` is never empty); every `## Architecture` component is a row in `mapping.json` with a status; every deferred component is bulleted by exact name and struck from `## Architecture`; every kept-by-principle entry names a citable `external_id` and a sentence; every `T<n>` is referenced; `## Mapping` mirrors `mapping.json`.

### Out of scope

- Adding a component — the sketch's; a test no component passes returns to the node (step 6), it is not patched here.
- Editing `## Options`, `## Decision`, or the `###` names — the sibling demis'; a rename is a return to the node.
- Deciding (b) on a principle that is not an initiative in the snapshot — "we always…" is not a declared principle; file the initiative through Daniel first if it should be one.
- Treating the `overbloat-review` verdict as a cut — it advises; the two-part rule decides. Do not skip the review because the sketch "looks lean".
- The gate and `set-node` — the node's, after you return.

### Deliverable format

- **Writes:** `<run-dir>/02_decide/principles.json`, `mapping.json`, `Deferred.md`; `Decision.md` `## Mapping` + `## Cuts`; the `overbloat-review` worklog entry per that skill's own discipline.
- **Returns (to the node):** the three paths · `N tests, C components (K kept-by-test, P kept-by-principle, D deferred)` · the overbloat score line · any `T<n>` no component passes — under 80 words.

### Escalate if

- `list_initiatives` fails or returns nothing readable → `BLOCKED`; do NOT write `principles.json` from memory or from the PRD's §5 table.
- A `T<n>` is passed by no kept component after (a) and (b) → return to the node (a missing component, or an unmeetable test → Daniel); do NOT map it to the nearest component to make the gate pass.
- (a) cuts and (b) keeps a component whose keep costs a week, not a line → return to Daniel with the initiative and the cost (PRD §3.2: *"the correct move would be to escalate the tension"*); do NOT cut silently and do NOT keep silently.
- A component in `## Architecture` has no `Passes` line and no clear (a) answer → return to the node for the sketch demi; do NOT guess a test id.

## Self-review

- [ ] Every name in `mapping.json` is byte-equal to a `###` heading; every deferred name is byte-equal to its `## Deferred` bullet.
- [ ] Every `principles` entry is an `external_id` present in `principles.json` with a citable state — I checked the state, not just the id.
- [ ] No component was kept on "(b) feels principled"; every keep-by-principle sentence names what the initiative commits us to.
- [ ] No deferred component still has a live `###` block in `## Architecture`; the `## Mapping` Status column matches the JSON.
- [ ] Placeholder scan: no `T?`, no `<external_id>` literal, no empty `## Overbloat review`.

## Gate contribution

Direct and total: `mapping.json` IS what `check_deciding` (`system/bin/node_gates.py`) reads at `gate-pass --node deciding --decision <path>` — it resolves `tests_file`, `deferred_file`, `principles_file` relative to the mapping's directory; refuses an unknown `T<n>`, an unknown or non-citable principle, a duplicate or nameless component, a test no component references, and an unmapped component not bulleted under `## Deferred`; lists every refusal at once. Exit 0 freezes all four files. **Unchecked by the gate:** whether (a) was answered honestly — the gate cannot tell "needed to pass T3" from "helps with T3". That is the delete-test in step 3 and the Self-review; the observed cost of getting it wrong is PRD §3.2's cut-then-un-cut, twice.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "No test needs it — cut it." | PRD §3.2: *"Part (a) said cut, and I cut it."* The cut left the fix-vs-pivot rule *"intact and unenforceable"*; Daniel un-cut it. §4: the propagation script, *"Failed cut-rule part (b)"*. Step 4 runs on every (a) cut, with the snapshot open. |
| "(b) says it's principled, so keep it." | Daniel, PRD §3.0: *"measure against the value it loses"*; *"having a quick fix go off the rails and become sessions of work is a frequent failure mode."* A keep names a citable `external_id` and the sentence; the check refuses an id that is archived or absent. |
| "It's marked v2; the section can stay." | Retrospective F1: *"The cut happened in the acceptance section and nowhere else."* A deferred component is struck from `## Architecture`; the `components` list is the v1 set. |
| "The Plan / PRD names this component, so it exists." | `OverbloatReview_gear2-understand` 2026-09-07: *"decomposition inherited from the plan, the bloat signature."* A document's shape is neither a test nor a principle; the component is deferred with that reason. |
| "The sketch is lean; skip the overbloat call." | PRD §3.N2: *"Calls `overbloat-review`; does not fold it (11 recorded invocations — it works)."* The review is cheap, its `shrink:` tag is the plan-inherited finding above, and an empty `## Overbloat review` fails the Self-review. |

## Source

- **Parent node:** `gear3-decide`
- **Origin:** Plan T4.4 `Note` (2026-08-27) — *"implements the two-part cut rule Daniel set, not the single-question version"*; PRD §3.0 (Daniel, 2026-08-27), §3.2, §4; chief-pm rulings 2026-09-07 (`BUILD_LEDGER.md`): file names and sections, the `mapping.json` shape, `T<n>` ids, `principles.json` as a faithful snapshot with the check filtering by state, `## Deferred` bullet parsing, `overbloat-review` placement.
- **Precedent failures:** `m4-loop/gear3-decide-baseline.md` rows 1, 2, 4, 5, 7.
- **Authored by:** chief-pm on 2026-09-07.
- **Lineage:** `derives_from: none` — the two-part rule is Daniel's (PRD §3.0), the mapping shape is this run's ruling, and `overbloat-review` is called, not adapted. Upstream `brainstorming`'s "YAGNI ruthlessly" is applied one demi earlier (option generation) and is not this file's structure.
- **Sibling demi-skills:** `demi-decide-option-generation`, `demi-decide-architecture-sketch`.
