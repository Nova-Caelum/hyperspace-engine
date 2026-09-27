---
name: demi-draft-prd-writing
description: "Demi-skill of gear4-draft. Emits 03_draft/PRD.md — the spec: v1 components from the frozen mapping, principles with Task Graph entries, the v2 recap, the prose-only-rules closeout."
disable-model-invocation: true
derives_from: brainstorming
license: MIT
author: Nova Caelum
version: 1.0
---

# Draft — PRD Writing

**Parent node:** `gear4-draft`
**Invocable:** No. Reached only by its parent node (step 2), inline or dispatched to a subagent by it.
**Emits:** `<run-dir>/03_draft/PRD.md` — eight fixed sections, in order

## Overview

Renders the frozen decision into the specification the plan argues from — a record, not a re-design. The Graph Machine PRD carried some 750 lines of architecture no gate required, with its cut recorded in the acceptance section and nowhere else; the author's three review items on this framework's own PRD — the principles with their Task Graph entries, a plain recap of v2, a closeout naming every rule enforced only by prose — exist because *"that context gets lost."* Here `## Components` is `mapping.json` rendered, the v2 recap is `Deferred.md` rendered, and nothing is designed.

## Dispatch shape

### Context

- **Anchor docs (READ THESE FIRST):**
  - `<run-dir>/02_decide/mapping.json` — frozen at N2; its `components` list IS the v1 set; an entry's `tests` (`T<n>`) and `principles` (initiative `external_id`s) are the only justification a component has
  - `<run-dir>/02_decide/Decision.md` — `## Decision` (the option taken, the reason, `Decided by:`), `## Architecture` (per component: **Does** / **Used by** / **Depends on** / **Passes**; `### Data flow`, `### Error handling`, `### Testing`), `## Cuts`
  - `<run-dir>/02_decide/Deferred.md` — `## Deferred` (bold-led bullets: the v2 set, each with its reopen clause), `## Kept by principle`, `## Overbloat review`
  - `<run-dir>/02_decide/principles.json` — the `list_initiatives` snapshot: `id`, `external_id`, `title`, `state`, `captured_at`
  - `<run-dir>/01_understand/tests.json` — `acceptance_criteria` numbered `T1..TN` in file order (every entry, `manual` included); `<run-dir>/01_understand/Problem.md` — `## Ask`, `## Problem`, `## Constraints`, `## Out of scope`, `## Assumptions Register`
  - `<run-dir>/loop.state.json` — must read `current_node: specifying`; its `driver` block says whether the user is present
  - source: the framework PRD, 2026-08-27 — the exemplar: its §1 (acceptance set), §2 (one page), §3 (component set derived, not chosen), §4 (the v2 cut list as a record), §5 (decisions inherited), §11 (not claimed) are the register; its §12 self-review record is a one-off that future PRDs do NOT carry (§12.0 point 1 — the checklist lives in this demi's body)
- **Locked decisions — do NOT re-open:** the frozen N1 and N2 files (any edit is a hash-detected double-back); D5 (N3 exits by the plan check; `taskgraph-closure` not applicable); the eight section names below (ruling of 2026-09-08 recorded in a prior run's build ledger — T4.6 renders the template from them); no reviewer subagent (Plan Durable Decisions; T4.5 `Note`).
- **Loop state:** node `specifying`; `01_understand/` and `02_decide/` frozen.

### Your task

Create `<run-dir>/03_draft/PRD.md` with exactly the eight sections below, in this order, each carrying content.

1. **Header.** `# PRD — <slug>` then one line: project code · run id · node `specifying` · driver · date · `Companion plan: 03_draft/Plan.md` · `Acceptance set: 01_understand/tests.json (frozen <first 8 of its sha256>)`. Then `**User reviewed:** no` (the review-signal line — written once, never touched again).
2. **`## Acceptance set`.** `T1..TN`, one line each: `T<n> — <verification.kind> — <statement, verbatim>`. Verbatim, because the criteria are frozen and a paraphrase is a second copy that drifts. Mark the `WHOLE-PATH:` entry and every `manual` entry as such at the end of its line.
3. **`## What we are building`.** One page at most; bounded runs, one screen. For a reader who has opened nothing else: the goal in one sentence (from `Problem.md ## Problem`), the option taken and its reason in one paragraph (from `Decision.md ## Decision`, naming the tests and constraints it cites), then every `## Constraints` line verbatim, marked HARD.
4. **`## Components`.** One `### <name>` per `mapping.json` component whose `tests` or `principles` is non-empty, in mapping order, name verbatim — it is the mapping key and the plan's `Path` / `Produces` anchor. Under each: **Does** / **Used by** / **Depends on** (from `## Architecture`, condensed, not re-thought), **Passes** `T<n>…` (from the mapping), **Kept by** `test` or `principle <external_id>`. No component the mapping lacks; nothing bulleted under `## Deferred` appears here. Close with `### Data flow`: the `WHOLE-PATH:` criterion walked from entry to terminal effect through the named components (from `Decision.md ### Data flow`).
5. **`## Principles`** (the first review item). One bullet per initiative cited in any `mapping.json` `principles` list: `**<external_id>** — <title> — Task Graph id \`<id>\` (state <state>) — keeps: <component name(s)> — <the one sentence from Deferred.md ## Kept by principle saying why cutting contradicts it>`. If no component is kept by principle, write the one line `No component is kept by principle in v1; snapshot <captured_at> held <N> live initiatives.` — the section's presence proves the check ran.
6. **`## v2 recap`** (the second review item). The bold-led bullets of `Deferred.md ## Deferred`, one line each: `**<name>** — <what it is, one plain clause> — reopen when: <the reopen clause, verbatim>`. **No reasoning** — not why it was cut, not what keeping it would have cost; a future agent reads this section to rebuild the v2 component list and nothing else. Close with one line, `v1 set: <the ## Components names, comma-separated>`, so the two lists sit side by side.
7. **`## Decisions inherited`.** A three-column table — decision · source · date — of what this spec rests on and does not re-argue: every `Problem.md ## Constraints` line; every verified row of its `## Assumptions Register`; `Decision.md ## Decision` with its `Decided by:`; every `Ruling:` in the run's ledger this spec depends on. Cite; never re-derive.
8. **`## Not claimed`.** What v1 does not deliver, from `Problem.md ## Out of scope` and the deferred set — including the uncomfortable line. A spec that claims everything is the one that shipped a mock as done.
9. **`## Closeout — rules enforced only by prose`** (the third review item). Every rule this document states that no script, validator, gate, fixture or test enforces — one line each: `<the rule, quoted from the section that states it> — enforced by: prose only — harden by: <the check that would enforce it, or "unknown">`. Scan your own `## What we are building`, `## Components` (**Does** / `### Data flow`), `Problem.md ## Constraints` and `Decision.md ### Error handling`. A rule with a named mechanism is not listed. If the scan finds nothing, write `None found — every rule above names its mechanism` and mean it.
10. **The user.** If `loop.state.json` says they are present: one question — accept the v1 set as rendered in `## Components`, or override — and record their answer verbatim as the last row of `## Decisions inherited`. If absent: append `Rendered by: <driver>, user absent` to the header line. Hand back to the node for step 3.

**Acceptance:** eight sections present, in order, each with content; `## Acceptance set` statements byte-equal to `tests.json`; `## Components` names equal the mapped components of `mapping.json`, no more, no fewer, none from `## Deferred`; every principle cited in the mapping appears in `## Principles` with its Task Graph id; every `## Deferred` bullet appears in `## v2 recap` with no reasoning clause; `## Closeout` lists every prose-only rule or the explicit none-found line; no `TBD` / `TODO` / `<…>` token; the user's answer recorded when they were present.

### Out of scope

- Designing anything — no new component, no renamed component, no re-weighed option. `gear3-decide` owns those and its files are frozen; a gap is a double-back to N2 through the node's stops, not a PRD addition.
- The plan, the workplan, the filing — `demi-draft-plan-writing`, `demi-draft-taskgraph-emit`.
- Restating the cut reasoning in `## v2 recap` — `Deferred.md` keeps it; the recap is names and reopen clauses.
- A self-review record INSIDE the PRD — the exemplar's §12 was a one-off; §12.0 point 1 moves the checklist here, below.

### Deliverable format

- **Writes:** `<run-dir>/03_draft/PRD.md`.
- **Returns (to the node):** the path · component count (kept-by-test / kept-by-principle) · v2 recap count · principles cited · closeout line count · who decided — under 60 words.

### Escalate if

- A mapped component has no `## Architecture` entry, or `## Architecture` names a component the mapping lacks → the N2 files disagree; return to the node naming both, do NOT reconcile them here.
- A cited principle is absent from `principles.json` or not in a live state → return to the node (the N2 gate should have refused it; say so), do NOT drop the citation silently.
- A `## Constraints` line is contradicted by `## Decision` → stop; return to the node naming both lines, do NOT soften the constraint.
- The user overrides the v1 set → that is a double-back to N2; record their words verbatim, return to the node, do NOT edit `mapping.json`.

## Self-review

Four checks, run by the author with fresh eyes on the finished file. **If a check fails, fix it inline and move on — no second pass, no re-review, no reviewer subagent.** Create a todo per item before running them.

- [ ] **Placeholder scan:** no `TBD`, `TODO`, `<…>` token, or empty section; no number that is a guess — an unset number says it is unset and why.
- [ ] **Internal consistency:** `## Components` names equal `mapping.json`'s mapped names; `## v2 recap` names equal `Deferred.md ## Deferred`'s; the two lists are disjoint; `## Acceptance set` is byte-equal to `tests.json`; no section contradicts another.
- [ ] **Scope check:** the spec is one goal — if `## Components` reads as two independent subsystems, that is a finding for the node (decompose at N1/N2), not two PRDs.
- [ ] **Ambiguity check:** every `## Closeout` rule reads one way only; every `## Principles` line names the component it keeps; any requirement that admits two readings is rewritten to one.

## Gate contribution

Indirect. `check_specifying` reads the Plan's `task_id` fields, not this file — the eight sections are checked by shape as of T4.6 (2026-09-08): render this file from the loop's `prd.template.md` template, which declares all eight as its `required_sections` in order, and run `.hyperspace/env/bin/python "${CLAUDE_PLUGIN_ROOT}/bin/template_lint.py" --template <prd.template.md> --document <run-dir>/03_draft/PRD.md`, which refuses a missing or out-of-order section, an unfilled `«FILL: …»` marker, and an empty section body. It is not wired into `check_specifying` (that would re-open the signed T4.8 table), and it cannot see whether a section's CONTENT is true — `## Closeout` is still where that gap is recorded for the run that reads it. What this demi contributes: the acceptance set the plan's `Serves` must cover (the emit demi's review computes that set difference before mapping), and the component names the plan's `Path` / `Produces` anchor to. The Self-review is the check.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The PRD is where the architecture gets written properly." | Retrospective F1: *"It is not a v1 spec with v2 deferrals. It is a v2-shaped architecture with a v1 label on the gates … The cut happened in the acceptance section and nowhere else."* `## Components` is the mapping rendered; a component the mapping lacks is a double-back to N2. |
| "The deferred list is in `Deferred.md`; the PRD needn't repeat it." | The author, PRD L511: *"a recap of what needs / will be built in v2. No why. … Alot of that context gets lost and i want to fix that."* `## v2 recap` — names and reopen clauses, no reasoning. |
| "The principles are on the graph; a name is enough." | The author, PRD L155: the section is *"listing the relevant initiatives and pointing to the taskgraph copy of it."* `external_id`, Task Graph id, state, and the component each one keeps. |
| "That rule is in the prose; it'll hold." | The author, PRD L61: *"a closeout doc that sets up for v2 a note that this maybe prose enforced in which case we may have to harden."* Eliminate-first rung 3 is a disclosed debt, not a mechanism; `## Closeout` is the ledger of it. |

## Source

- **Parent node:** `gear4-draft`
- **Origin:** Plan T4.5 `Note` (the author's three PRD-template items, 2026-08-27); PRD §12.0 (the checklist lives in this demi's body, not in the artifact); PRD L155 / L511 / L61 (the three notes, verbatim); rulings of 2026-09-08 recorded in a prior run's build ledger: the eight section names; the closeout as a section of `PRD.md`; `## v2 recap` = the deferred set.
- **Precedent failures:** an internal baseline record, 2026-09-07 rows 6 (the three notes), 7 (retrospective F1).
- **Authored by:** the engine's authors on 2026-09-07.
- **Community lineage:** obra/superpowers `brainstorming` 6.3.0 (MIT), archived with the framework's research notes §"After the Design (architectural path)". Ported: write the validated design to a spec file the plan argues from; the four-item Spec Self-Review — placeholder scan, internal consistency, scope check, ambiguity check — with the clause *"Fix any issues inline. No need to re-review — just fix and move on"*; the User Review Gate reduced to the user's one accept/override question when they are present. Not ported: the `docs/superpowers/specs/` path and its commit step; the elements-of-style call; the User Review Gate as a blocking wait (the plan gate is the gate); the writing-plans handoff (the node's step 3 is fixed); the visual companion; per-section approval. Port / no-port table: an internal derivation-scope record, 2026-09-07.
- **Sibling demi-skills:** `demi-draft-plan-writing`, `demi-draft-taskgraph-emit`.
