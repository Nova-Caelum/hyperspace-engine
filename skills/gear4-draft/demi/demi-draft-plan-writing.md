---
name: demi-draft-plan-writing
description: "Demi-skill of gear4-draft. Emits 03_draft/Plan.md — the plan in the task-block format the uploader parses: every field present, task_id blank until filing, plan_lint clean."
disable-model-invocation: true
derives_from: writing-plans
license: MIT
author: Nova Caelum
version: 1.0
---

# Draft — Plan Writing

**Parent node:** `gear4-draft`
**Invocable:** No. Reached only by its parent node (step 3), inline or dispatched to a subagent by it.
**Emits:** `<run-dir>/03_draft/Plan.md` — `##` modules, `####` task blocks, eleven fields each, `task_id` empty

## Overview

Turns the specification into the plan the uploader parses and the Build node executes. The first draft of this framework's own Plan dropped Context on every task for density and was judged *"not even vaguely stand alone"*; the uploader's first run then located 0 of 45 `task_id` fields in it and printed PASS. The format here is the parser's contract (Plan L77: *"the nesting is the module-to-work-item relationship"*), the reader of every block is a fresh implementer with no history, and `plan_lint` is the mechanical half of this demi's self-review.

## Dispatch shape

### Context

- **Anchor docs (READ THESE FIRST):**
  - `<run-dir>/03_draft/PRD.md` — `## Acceptance set` (every entry must land on ≥1 task's `Serves`), `## Components` (names are the anchors for `Path`, `Produces`, `Interfaces`), `## Not claimed`
  - `<run-dir>/02_decide/mapping.json` — the component ↔ `T<n>` map; a task's `Serves` is drawn from the tests its component passes
  - `<run-dir>/01_understand/tests.json` — the typed criteria the emit stage carries into the rows (`verification.kind`, `path` / `target`); the plan's `Acceptance criterion` fields are the prose form of these and of nothing else
  - `AgentSecretBase/workspace/hyperspace-engine_new_sprintframework/Plan_NovaCaelumFramework_ChiefPM_2026-08-27.md` — THE format: the header (L1–8), `## The task block format, and why each field exists` (L38–57), one module block (`## M4`, L555–561), one task block (`#### T4.5`, L630–644); `plan_lint` CLEAN on the whole document
  - `_agentOS/system/bin/plan_lint.py` — the eleven `FIELD_NAMES` and rules S1–S6; run it, never reimplement it
  - `_agentOS/skills_library/taskgraph-write/SKILL.md` §12 — the two refused criterion shapes (a `<…>` token where the value is knowable; `exists` on a path already present); the plan's `Acceptance criterion` and `Produces` are where they are avoided, because the emit stage carries them verbatim
  - `_agentOS/skills_library/gear5-build/SKILL.md` step 3 and `gear5-build/demi/demi-build-subagent-dispatch.md` — who reads a task block: a fresh implementer, briefed from the block, with no conversation history
  - `<run-dir>/loop.state.json` — must read `current_node: specifying`
- **Locked decisions — do NOT re-open:** `PRD.md` as the sibling wrote it (a plan that cannot cover it is a finding for the node, not a PRD edit); the task-block format and its eleven fields (Plan Durable Decisions: *"Every task carries a plain-language `Summary`, a `Path`, and a `task_id` backfilled at filing"*); Daniel's per-task caps — 1 fresh session · 1 compaction · 2 real-time hours · 3 worklog entries — cited, never re-derived; no reviewer subagent.
- **Loop state:** node `specifying`; `01_understand/`, `02_decide/` frozen; `03_draft/PRD.md` written.

### Your task

Create `<run-dir>/03_draft/Plan.md`.

1. **Header.** `# Plan — <slug>` · `**Project code:** \`<projects.code>\`` · `**Companion PRD:** \`03_draft/PRD.md\`` · `**Author:** <driver> · <date>` · `**Daniel reviewed:** no` · `**Acceptance set:** 01_understand/tests.json — <N> criteria, <E> executable, <M> manual` · `**Modules:** <m> · **Tasks:** <t> · **External-id namespace:** \`<prefix>-\``. The namespace is the project's row prefix; every `external_id` below begins with it (`plan_lint` S4).
2. **Files before tasks.** `## Files` — a table, one row per file the v1 set creates or modifies: path · component (from `PRD.md ## Components`) · created / modified · owner. This is where decomposition locks: a task is drawn around files that change together, one responsibility each; the task blocks cite this table rather than re-deciding it.
3. **Modules.** `## M<n> — <imperative title>` per component group (a module may hold one component), each carrying `**external_id:** \`<prefix>-m<n>-<slug>\``, `**Owner:**`, `**Summary:**` (plain English), `**Acceptance criteria:**` (the module's done-definition, 20–2000 chars), `**Blocked by:**`. Every module has ≥1 task — an empty module is a step never broken down, and the uploader refuses it.
4. **Task blocks.** `#### T<n>.<m> — <imperative sentence>` under its module, carrying ALL eleven field markers in this order, each as `- **<name>:** <value>`:
   `task_id` — **EMPTY**: `- **task_id:** ` and nothing after the colon; the uploader writes the identifier the Task Graph hands back · `external_id` — `\`<prefix>-…\``, unique across the document · `Owner` — one persona name · `Summary` — one or two sentences of plain English: no acronyms, no criterion codes, no task numbers, no section references; readable with no other document open · `Blocked by` — named upstream work in words, or `none` · `Path` — the exact file edited, or the folder a new file lands in · `Serves` — the `T<n>` codes this task discharges (codes live here, deliberately, so `Summary` stays plain) · `Acceptance criterion` — observable; someone else runs it and gets yes or no; false today; no `<…>` token where the value is knowable now; the emit stage carries it into the row verbatim · `Budget` — size class plus a session estimate against Daniel's caps; a task over the cap says so in this field · `Interfaces` — `*Consumes:*` what it uses from earlier tasks, by name; `*Produces:*` EVERY file it creates, in full, by its decided path — never "the thing it makes" · `Note` — the reasoning, the anchor incident, the trap to avoid.
5. **Right-size.** A task is the smallest unit that carries its own acceptance criterion and is worth a verifier's verdict — `complete_workitem` closes one row at a time. Fold setup, configuration, scaffolding and docs into the task whose deliverable needs them; split only where a verifier could refuse one task and pass its neighbour. **A `manual` criterion is never a task of its own** — the contract refuses a row whose criteria are all `manual` (*"All-manual criteria cannot be discharged by node 6 and therefore cannot support a completion claim"*), so an attestation rides on the task whose deliverable it judges; splitting it out to unblock that task's machine evidence produces a row the emitter will not file, and adding an executable criterion to carry it is the restating-criterion shape Self-review item 1 already refuses. Order tasks by the dependencies `Blocked by` names.
6. **Lint, then hand back.** `python3 $AGENTOS_ROOT/system/bin/plan_lint.py <run-dir>/03_draft/Plan.md` → `CLEAN: … no plan-format violations`. Fix every violation it names before the Self-review below; then hand back to the node for step 4.

**Acceptance:** `plan_lint` CLEAN; every task block carries all eleven markers with `task_id` empty; every `PRD.md ## Acceptance set` entry appears in ≥1 `Serves`; every `Produces` entry is a full decided path; every `Acceptance criterion` can be false today and carries no `<…>` token where the value is knowable; every module has ≥1 task; every `external_id` unique and namespaced.

### Out of scope

- Filling `task_id` — the uploader's. A hand-typed value is refused at the gate (not a UUID), or worse, passes it: a UUID that names no row is a plan lying about being filed, and the emitter refuses to overwrite a non-blank value (`taskgraph_emit.py` L493–497, reported as a conflict), so the row files and the Plan keeps the fiction.
- Editing `PRD.md`, `mapping.json`, `tests.json` — frozen or sibling-owned; a plan gap is a finding for the node.
- `workplan.json`, `validate` / `plan` / `apply` — `demi-draft-taskgraph-emit`.
- Step-by-step code inside a task (write the failing test, run it, implement, run, commit) — upstream's bite-sized steps are `gear5-build`'s `demi-build-tdd` at execution time, not plan content; a task block briefs an implementer, it does not implement.

### Deliverable format

- **Writes:** `<run-dir>/03_draft/Plan.md`.
- **Returns (to the node):** the path · module and task counts · the `plan_lint` line · acceptance-set coverage (`<served> of <N>`) · any task over Daniel's caps, by label — under 60 words.

### Escalate if

- An acceptance-set entry has no task that can serve it → return to the node naming `T<n>` (a design gap goes back to N2); do NOT invent a task that "covers" it by restating it.
- A task's honest `Budget` exceeds the caps → write it in the field and hand back; the node's stops carry it to Daniel (defer · promote to module · abandon); do NOT split it into pieces that each hide the overrun.
- `plan_lint` names a violation you cannot fix without renaming a component → return to the node; names are the mapping's keys and the PRD's anchors.

## Self-review

Three checks, run by the author with fresh eyes on the finished file, after `plan_lint` is CLEAN. **If a check fails, fix it inline and move on — no second pass, no re-review, no reviewer subagent.** Create a todo per item before running them.

- [ ] **Spec coverage:** walk `PRD.md ## Acceptance set` top to bottom; for each `T<n>` point at the task whose `Serves` carries it; list the gaps and add the task — or return to the node if the gap is a design gap.
- [ ] **Placeholder scan:** no `TBD`, `TODO`, "implement later", "add appropriate error handling", "similar to T<n>", "write tests for the above"; no `<…>` token in a `Path`, `Produces` or `Acceptance criterion` where the value is knowable now; no `task_id` with anything after the colon.
- [ ] **Name consistency:** every component, file path and interface name a later task uses matches the earlier task that produces it and matches `PRD.md ## Components` — `parity_test.py` in T1.1 and `test_contract_parity.py` in T1.3 is a bug.

## Gate contribution

Direct, in two halves. **Shape:** `plan_lint` CLEAN (step 6) — `check_specifying` reuses `plan_lint`'s parser, so a malformed block is invisible to the gate rather than refused by it; the lint is what makes the gate's block count honest. **Identifiers:** the gate's own — `check_specifying` refuses every `####` block whose `task_id` is blank or not UUID-led, which is why this demi leaves the field empty for the uploader to fill (Plan L63: draft → emit → backfill → gate → freeze). Checked by: `plan_lint.py` (here) · `node_gates.check_specifying` via `gate-pass --node specifying --plan` (node step 5) · fixture `exit-gate/draft-blank-task-id` · and, for the two things `plan_lint` does not cover, `template_lint.py` against `_agentOS/skills_library/_meta/templates/loop/plan.template.md` — that `## Files` exists and that no `«FILL: …»` marker survived. The template declares only `## Files` as required, on purpose: module and task headings are variable, and `plan_lint` already enforces the eleven markers more strictly than a heading list could. Run both; neither is a subset of the other.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The task is obvious from the plan's flow; the fields are padding." | Plan L40: *"fails to provide enough context to be considered even vaguely stand alone"* — the first draft *"dropped Context on every task in favour of density."* L42: *"maximizing durable context, minimizing what gets lost in a session context."* Eleven fields, every block. |
| "The implementer will name the file; the plan says what it makes." | Plan L56: *"A task whose output is 'the thing it makes' is not plannable by an agent that cannot see this conversation."* `Produces` names every file by its decided path. |
| "It validated, so the criterion files." | `taskgraph-write` L127: *"seven filed criteria carried `<date>` copied from a plan's `Produces` field. Work finished, hashes recorded, and the Graph Machine still refused the `done` flip."* The plan is where a criterion is made honest; the emitter carries it verbatim. |
| "I'll fill the `task_id` now so the gate passes." | `taskgraph_emit.py` L493–497: *"A line carrying some other non-blank value is never overwritten — it is reported as a conflict instead."* The row files, the Plan keeps a UUID that names nothing, and the gate passes on a fiction. Empty until `apply`. |

## Source

- **Parent node:** `gear4-draft`
- **Origin:** Plan T4.5 (`Interfaces › Consumes: this plan's own format as the template`); Plan `## The task block format, and why each field exists` (Daniel review 2026-08-27); Plan Durable Decisions (`task_id` backfilled at filing; `Summary` and `Path` on every task); chief-pm rulings 2026-09-08 (`BUILD_LEDGER.md`): `Plan.md` shape; `task_id` empty when drafted; `plan_lint` CLEAN as the mechanical self-check.
- **Precedent failures:** `m4-loop/gear4-draft-baseline.md` rows 1 (PASS with nothing backfilled), 2 (stand-alone context), 3 (`Produces` by path), 8 (`<date>` criteria).
- **Authored by:** chief-pm on 2026-09-07.
- **Community lineage:** obra/superpowers `writing-plans` 6.3.0 (MIT), archived at `01_research/upstream-source-6.3.0/skills/writing-plans/SKILL.md`. Ported: File Structure before tasks (step 2); Task Right-Sizing (step 5); the plan header carrying the goal, the spec pointer and the global constraints (step 1, in our field names); `Files:` / `Interfaces:` per task (our `Path` and `Interfaces`); the No Placeholders list as plan failures (Self-review item 2); the three-item Self-Review — spec coverage, placeholder scan, type/name consistency — with *"If you find issues, fix them inline. No need to re-review — just fix and move on"*. Not ported: bite-sized 2–5-minute steps with code blocks (execution-time content, `demi-build-tdd`); the `REQUIRED SUB-SKILL` header line; the `docs/superpowers/plans/` path; the Execution Handoff choice (`gear5-build` is the only door); `plan-document-reviewer-prompt.md`; the worktree line; the announce-at-start line. Port / no-port table: `m4-loop/DerivationScope_gear4-draft_ChiefPM_2026-09-07.md`.
- **Sibling demi-skills:** `demi-draft-prd-writing`, `demi-draft-taskgraph-emit`.
