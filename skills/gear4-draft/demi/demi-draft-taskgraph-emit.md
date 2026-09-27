---
name: demi-draft-taskgraph-emit
description: Emits a finished plan into the Task Graph. Owned by N3 Draft; produces filed module and work-item rows plus the gate verdict that closes the node. Not independently invocable.
disable-model-invocation: true
derives_from: none
---

<!--
  DEMI-SKILL. Bundled behind the N3 Draft node skill. NOT independently invocable.
  Mechanism: the `hyperspace` MCP server's graph tools — `upsert_module`,
  `upsert_work_item`, `link_work_items`, `get_work_item` — one call per object.
  Parent node skill `gear4-draft` — this demi is its step 4.
  Lineage: derives_from is `none` (the author, 2026-09-08). The source engine filed
  through a batch uploader script; this plugin files through the graph tools directly
  (the plugin PRD's data flow, step 3), and the gate is unchanged.
-->

# demi-draft-taskgraph-emit

## Context

You are closing **N3 Draft**. A PRD and a Plan exist. Your job is to make the plan
*tracked work* rather than a document.

**This is a gate, not a convenience.** The author, 2026-08-27: *"taskgraph emit should be
the end of the draft node. It signals and gates transition to the next node. We do not
build if there's no guide in the task graph."*

N3 does not close until every plan step exists as a row and the Plan carries that row's
identifier. If this fails, the node **holds**. You do not proceed to N4 Build.

Every prior stall in this system has one shape: a planning artifact exists on disk and
nothing downstream ever reads it. `make-it-happen` has zero formal invocations and one
artifact trail dead at P2. `superpowers:writing-plans` has zero invocations ever, and
its mandated output directory never existed anywhere in the source workspace. **A plan
that never becomes tracked work is indistinguishable from a plan nobody wrote.**

### Anchor docs

- source: the framework PRD, 2026-08-27, §3.3 — why this is a gate
- `hyperspace/contracts/candidate.py` (in the plugin) — `CandidateWorkItem`, the contract
  every filed work item is validated against
- `03_draft/PRD.md` and `03_draft/Plan.md` — the pair you are filing

## Your task

Three stages, in order. Nothing is filed until the first two pass.

### 1. Review — is this a real plan, and does it match its PRD?

- Locate the companion PRD. A Plan with no PRD is not reviewable and this stage fails.
- Read both. Confirm the plan's steps deliver what the PRD's acceptance set requires.
- **The check that matters:** every acceptance criterion in the PRD appears on at least
  one plan step. An orphan criterion means the plan does not deliver v1 — a set
  difference, not an impression.
- If they do not align, **stop and report**. Do not file a plan you could not verify.

### 2. Map — plan prose to `workplan.json`

Write one JSON file, `03_draft/workplan.json`. It is the mapping record: the gate
freezes it, and the Build gate reads its `project` and `work_items[].external_id` to
know which rows the run owes.

```jsonc
{
  "project": "<projects.code>",
  "source_plan": "<project-root-relative path to the Plan doc>",
  "source_prd":  "<project-root-relative path to the PRD>",
  "modules": [
    { "external_id": "...", "name": "...",
      "acceptance_criteria": "<prose, 20-2000 chars>", "state": "ready" }
  ],
  "work_items": [ /* each a full CandidateWorkItem, one per #### task block */ ],
  "relations": [
    { "item": "...", "related_item": "...", "relation_type": "blocked-by" }
  ]
}
```

Rules the contract and the graph tools enforce, so getting them right first is cheaper:

- **Modules are plan sections; work items are plan steps.** The nesting in the document
  *is* the module↔work-item relationship. Every module must have at least one child — an
  empty module is a plan step that was never broken down. Placement: a thing other work
  items hang off as independent deliverables is a **module**; a single deliverable one
  agent owns end to end is a **work item**; a step inside another work item is a
  `parent_work_item`, not a sibling.
- **Every work item is a full `CandidateWorkItem`**: `specification` (problem /
  why_it_matters / context_pointer — each a real statement; placeholder text such as
  `TBD`, `TODO` or "to be determined" is refused), `acceptance_criteria` (typed, 1–20, at
  least one non-`manual`), `source_references` (≥1), `effort_level` (never null),
  `module` (key required, `null` allowed), `uncertainty_notes` (key required, may be
  empty), `idempotency_key`. A `path` or `target` is project-relative — no `..`, no
  leading `/` or `~` — and carries `<…>` only as one of the four filing tokens
  (`<date>`, `<run-id>`, `<slug>`, `<project>`). `exists` on a path already present is
  true before the work starts: assert what the work changes instead.
- **Fill the fields that get silently skipped**: link the PRD and plan in
  `source_references`, set `effort_level` honestly (`unknown` is a legitimate
  no-estimate signal, a guess is not), assign `assignee_agent` where the plan names an
  owner, and resolve every `Blocked by` line into a declared edge (below).
- **Turn each `Blocked by` line into a declared dependency edge.** A plan step's
  dependency is written as a `**Blocked by:**` line in free prose. Read each one, work
  out which work items of THIS plan it names, and add them to `relations` as
  `{ "item": <the step that IS BLOCKED>, "related_item": <the step that BLOCKS it>,
  "relation_type": "blocked-by" }`. Both endpoints are work items in this same workplan;
  no self-edge; no duplicate triple. A `Blocked by` of **nothing** emits no edge —
  silence is legal. One line may name several upstream steps: one edge per step. If a
  line names work outside this plan, or something you cannot map to an `external_id`,
  say so in your review rather than guessing an edge.

  **Never reach for `parent_work_item` to express a dependency.** It is subtask
  semantics, not dependency; laundering one into the other corrupts the item tree.
- **Carry the plan's acceptance criteria verbatim.** Do not paraphrase them into new
  words. The plan's criterion and the filed criterion must be the same claim, or the two
  drift and the gate stops meaning anything.

### 3. File — one tool call per object, then backfill by hand

All calls go to the `hyperspace` MCP server.

1. Each module: `upsert_module` with its `external_id`, `name`, `acceptance_criteria`,
   `state`.
2. Each `####` task block, one at a time: `upsert_work_item` with that block's
   `CandidateWorkItem` from `workplan.json`, exactly as mapped. The tool validates the
   contract and refuses a missing or placeholder criterion; a refusal names the field —
   fix the workplan entry (and the Plan, if the Plan is where the defect is) and call
   again.
3. Read the row back with `get_work_item`. Only a row that reads back exists.
4. Write the returned row `id` into that block's `task_id` field in `Plan.md` —
   `- **task_id:** <id>` — by hand, in the same turn. Never type an identifier the tool
   did not return: a UUID that names no row passes the gate and breaks Build.
5. After every block is filed: each `relations` edge through `link_work_items`.

Idempotency keys make a re-call update the row rather than duplicate it, so a session
that dies halfway resumes by calling again for the blocks whose `task_id` is still empty.

## Gate contribution

**N3 Draft exits through `gate-pass --node specifying --plan <Plan.md>`,** which reads
the Plan and refuses any `#### T<n>.<m>` block whose `task_id` is blank or not a UUID.
The order is draft → file → backfill → gate → freeze; a backfill after the gate edits a
frozen artifact and counts as a double-back.

| Situation | What you do |
|---|---|
| Every block filed, read back and backfilled | Hand back to the node for the gate |
| A tool call refuses the payload | **Node holds.** Fix the workplan entry and call again |
| A tool call fails on transport | **Node holds.** Infrastructure, not your mapping — report it |
| Some blocks filed, some not | **Node holds.** Call again for every block with an empty `task_id` |

## Out of scope

- **Do not file anything outside the graph tools.** If a tool refuses, the payload is
  wrong. Filing around a refusal is the universal bypass this design exists to close, and
  it is the same move as *"the chain failed, so I'll write directly."*
- **Do not edit the PRD or the Plan to make mapping easier.** The one Plan edit this
  demi makes is the `task_id` backfill. If the plan genuinely cannot be mapped, that is a
  finding about the plan.
- Do not create projects. The project must already exist.
- Do not invent `effort_level` or acceptance criteria that the plan does not contain.

## Escalate if

- The plan and PRD do not align — report the specific gap; do not map around it.
- A plan step's level is genuinely ambiguous between module and work item after
  applying the placement rule above.
- A tool call fails on transport or auth. Not yours to fix.
- A tool refuses and you believe the refusal is wrong. **Say so; do not route around
  it.** A gate you can talk yourself past is not a gate.

## Why the gate reads the Plan, not the tool's answer

The source engine's first filing mechanism printed PASS on a plan where it had located
0 of 45 identifier fields and backfilled nothing. A receipt, an exit code or a success
message is not a row. The gate therefore reads the identifier written into the Plan, and
this demi reads every row back before writing it there.

## Source

Author-directed 2026-08-27, mid-PRD-review: *"some deterministic mechanism that takes a
finished plan and faithfully and accurately adds it to taskgraph is essential. And a
gap."* In the plugin the mechanism is the graph tools, called once per object, with the
identifier backfill done in the same turn (plugin PRD, data flow step 3).
