---
name: demi-draft-taskgraph-emit
description: Emits a finished plan into the Task Graph. Owned by N3 Draft; produces filed module and work-item rows plus the gate verdict that closes the node. Not independently invocable.
disable-model-invocation: true
derives_from: none
---

<!--
  DEMI-SKILL. Bundled behind the N3 Draft node skill. NOT independently invocable.
  Template: _agentOS/skills_library/_meta/templates/demi-skill.template.md
  Mechanism: _agentOS/system/bin/taskgraph_emit.py
  Status: mechanism BUILT AND PROVEN (2026-08-27, live write verified, row 1493cc28).
          Parent node skill `gear4-draft` AUTHORED 2026-09-07 (T4.5) — this demi is its
          step 4. Wiring-chain layers 3-9: M5.
  Lineage: derives_from is `none` (Daniel, 2026-09-08 — `sprint-manager` is retired
          and nothing routes to or leans on it). The mechanism is Daniel-directed
          (ForkNote 2026-08-27); the dispatch shape is the demi-skill template's.
-->

# demi-draft-taskgraph-emit

## Context

You are closing **N3 Draft**. A PRD and a Plan exist. Your job is to make the plan
*tracked work* rather than a document.

**This is a gate, not a convenience.** Daniel, 2026-08-27: *"taskgraph emit should be
the end of the draft node. It signals and gates transition to the next node. We do not
build if there's no guide in the task graph."*

N3 does not close until every plan step exists as a row. If this fails, the node
**holds**. You do not proceed to N4 Build and you do not file the rows by hand.

Every prior stall in this system has one shape: a planning artifact exists on disk and
nothing downstream ever reads it. `make-it-happen` has zero formal invocations and one
artifact trail dead at P2. `superpowers:writing-plans` has zero invocations ever, and
its mandated output directory does not exist anywhere in the vault. **A plan that never
becomes tracked work is indistinguishable from a plan nobody wrote.**

### Anchor docs

- `AgentSecretBase/workspace/hyperspace-engine_new_sprintframework/PRD_NovaCaelumFramework_ChiefPM_2026-08-27.md` §3.3 — why this is a gate
- `AgentSecretBase/workspace/hyperspace-engine_new_sprintframework/ForkNote_WorkplanUploader_ChiefPM_2026-08-27.md` — the three-stage design and its decisions
- `_agentOS/graph_library/contracts/candidate.py` — `CandidateWorkItem`, the live contract this validates against
- `_agentOS/skills_library/taskgraph-placement/SKILL.md` — module vs work_item, if a plan step's level is genuinely unclear

## Your task

Three stages. **You do the first two. The script does the third, and only the script
writes.**

### 1. Review — is this a real plan, and does it match its PRD?

- Locate the companion PRD. A Plan with no PRD is not reviewable and this stage fails.
- Read both. Confirm the plan's steps deliver what the PRD's acceptance set requires.
- **The check that matters:** every acceptance criterion in the PRD appears on at least
  one plan step. An orphan criterion means the plan does not deliver v1 — a set
  difference, not an impression.
- If they do not align, **stop and report**. Do not map a plan you could not verify.

### 2. Map — plan prose to `workplan.json`

Emit one JSON file:

```jsonc
{
  "project": "<projects.code>",
  "source_plan": "<vault-root-relative path to the Plan doc>",
  "source_prd":  "<vault-root-relative path to the PRD>",
  "modules": [
    { "external_id": "...", "name": "...",
      "acceptance_criteria": "<prose, 20-2000 chars>", "state": "ready" }
  ],
  "work_items": [ /* each a full CandidateWorkItem */ ],
  "relations": [
    { "item": "...", "related_item": "...", "relation_type": "blocked-by" }
  ]
}
```

Rules the script enforces, so getting them right first is cheaper:

- **Modules are plan sections; work items are plan steps.** The nesting in the document
  *is* the module↔work-item relationship. Every module must have at least one child — an
  empty module is a plan step that was never broken down.
- **Every work item is a full `CandidateWorkItem`**: `specification` (problem /
  why_it_matters / context_pointer), `acceptance_criteria` (typed, ≥1 executable),
  `source_references`, `effort_level`, `uncertainty_notes`, `idempotency_key`.
- **Fill the fields that get silently skipped** — this is the part a script cannot do
  for you: link the PRD and plan in `source_references`, set `effort_level` honestly
  (`unknown` is a legitimate no-estimate signal, a guess is not), assign
  `assignee_agent` where the plan names an owner, and resolve every `Blocked by` line
  into a declared edge (below).
- **Turn each `Blocked by` line into a declared dependency edge.** A plan step's
  dependency is written as a `**Blocked by:**` line in free prose — *"nothing"*, *"the
  harness runner"*, *"the work-item filing path being fixed, then the uploader being
  promoted and deployed"*. Read each one, work out which work items of THIS plan it
  names, and emit them into the workplan's top-level `relations` array:

  ```json
  "relations": [
    { "item": "<external_id of the step that IS BLOCKED>",
      "related_item": "<external_id of the step that BLOCKS it>",
      "relation_type": "blocked-by" }
  ]
  ```

  Rules the writer enforces, so getting them right here is cheaper: both endpoints must
  be work items declared in this same workplan; no self-edge; no duplicate triple;
  `relation_type` is `blocked-by` and nothing else in v1. A `Blocked by` of **nothing**
  emits no edge — that is silence, and silence is legal. One line may name several
  upstream steps: emit one edge per step.

  **This resolution is yours and cannot be delegated to the script.** `taskgraph_emit.py`
  never reads a markdown plan — *"If it had to interpret prose it would be making
  judgment calls, and a mechanism that guesses is the thing the split exists to
  prevent."* If a `Blocked by` line names work outside this plan, or names something you
  cannot map to an `external_id`, say so in your review rather than guessing an edge.

  **Never reach for `parent_work_item` to express a dependency.** It is subtask
  semantics, not dependency; laundering one into the other corrupts the item tree. That
  was ruled explicitly (`HANDOFF_TaskGraphWritePath_ChiefPM_2026-08-28.md` §B8), and it
  is why the `relations` array exists at all.
- **Carry the plan's acceptance criteria verbatim.** Do not paraphrase them into new
  words. The plan's criterion and the filed criterion must be the same claim, or the two
  drift and the gate stops meaning anything.

### 3. Emit — run the script

```bash
python3 _agentOS/system/bin/taskgraph_emit.py plan  <workplan.json>   # dry run
python3 _agentOS/system/bin/taskgraph_emit.py apply <workplan.json>
```

Read the dry run before applying. Then apply.

## Gate contribution

**N3 Draft's exit gate is `apply` exiting zero.** Nothing else closes the node.

| Exit | Meaning | What you do |
|---|---|---|
| 0 | Every row filed | Node closes. Record it in `loop.state.json` and proceed to N4 |
| 1 | Validation failed, nothing written | **Node holds.** Fix the JSON and re-run |
| 2 | Transport or auth failure, nothing written | **Node holds.** This is infrastructure, not your mapping — report it |
| 3 | **Partial** — some rows landed | **Node holds.** Re-run `apply`; idempotency keys mean filed rows update rather than duplicate |

## Out of scope

- **Do not file rows by hand.** If the script refuses, the plan is wrong. Filing around a
  refusal is the universal bypass this design exists to close, and it is the same move as
  *"the chain failed, so I'll write directly."*
- **Do not edit the PRD or the Plan to make mapping easier.** They are N3's frozen output.
  If the plan genuinely cannot be mapped, that is a finding about the plan.
- Do not create projects. The project must already exist.
- Do not invent `effort_level` or acceptance criteria that the plan does not contain.

## Escalate if

- The plan and PRD do not align — report the specific gap; do not map around it.
- A plan step's level is genuinely ambiguous between module and work item after
  consulting `taskgraph-placement`.
- Exit code 2 — auth or transport. Not yours to fix.
- The script refuses and you believe the refusal is wrong. **Say so; do not route around
  it.** A gate you can talk yourself past is not a gate.

## How the write reaches the Task Graph

Through **`ops_upload_workplan`** — a batch verb on ops-server 0.9.4, scoped to the
dedicated `workplan-uploader` identity, absent from `tools/list`, and gated on resolved
client identity before the body is parsed.

**It deliberately ignores `conversion_stage` and the canary-persona list.** That is the
whole reason it exists. Until 2026-08-27 this gate wrote through `upsert_work_item`,
which branches on the candidate's **self-reported** `proposer_identity`: a payload
proposed by `chief-pm` filed a row, and the byte-identical payload proposed by
`engineer` returned an `AdmissionReceipt` and filed nothing — while the gate printed
PASS. Proven by controlled test, one variable, same server, same hour.

Two consequences worth keeping in view:

- **A receipt is not a row.** A proposal is queued *adjudication*, not queued filing —
  the chain may legitimately never file it, or may attempt the work instead of recording
  it. The emitter therefore reads every row back and fails the gate on anything that did
  not materialize. Do not weaken that check; it is what makes this gate mean something.
- **Batch atomicity is validation-atomic, not transaction-atomic.** Validation rejects
  the whole batch before any write, but the writes themselves are sequential — there is
  no stored procedure behind them. A mid-batch server failure can therefore leave a
  partial batch, which surfaces as exit 3, not as a silent pass. Stated because it is a
  real limit, not a theoretical one.

## Source

Daniel-directed 2026-08-27, mid-PRD-review: *"some deterministic mechanism that takes a
finished plan and faithfully and accurately adds it to taskgraph is essential. And a
gap."* Design and split recorded in `ForkNote_WorkplanUploader_ChiefPM_2026-08-27.md`.
Mechanism proven end to end the same day against `graph-machine-testbed` — module
`b4aa7551`, work item `1493cc28`.
