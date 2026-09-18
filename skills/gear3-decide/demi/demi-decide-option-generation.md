---
name: demi-decide-option-generation
description: Demi-skill of gear3-decide. Emits 02_decide/Decision.md §Options and §Decision — two or three approaches weighed against the frozen tests and constraints, and the one chosen.
disable-model-invocation: true
derives_from: brainstorming
license: MIT
author: Nova Caelum
version: 1.0
---

# Decide — Option Generation

**Parent node:** `gear3-decide`
**Invocable:** No. Reached only by its parent node (step 2), inline or dispatched to a subagent by it.
**Emits:** `<run-dir>/02_decide/Decision.md` — `## Options` and `## Decision` (the file's first two sections; this demi creates the file)

## Overview

Turns a frozen test set and a constraints list into two or three genuinely different ways to pass the tests, each weighed line by line against every `T<n>` and every HARD constraint, and one of them chosen with the reason stated. `demi-decide-architecture-sketch` sketches only the chosen option; a wrong choice here is the most expensive sentence at N2.

## Dispatch shape

### Context

- **Anchor docs (READ THESE FIRST):**
  - `<run-dir>/01_understand/tests.json` — frozen at the N1 gate; number `acceptance_criteria` `T1..TN` in file order (every entry, `manual` included) and use only those ids
  - `<run-dir>/01_understand/Problem.md` — `## Problem`, `## Constraints` (each HARD), `## Out of scope`, `## Path` (bounded | architectural — the node already chose; you do not re-triage), `## Assumptions Register`
  - `<run-dir>/loop.state.json` — must read `current_node: deciding`; its `driver` block says whether Daniel is present
  - `_agentOS/skills_library/assumption-check/SKILL.md` — called (step 4) when an option's feasibility rests on a tool or platform behaviour nobody has verified; never folded
  - `$VAULT_ROOT/.claude/rules/frame-discipline.md` Context 2 — requirement → architecture → tool; stated requirements are HARD
  - `AgentSecretBase/_wiki/incidents/2026-06-21_INC014_vault-mcp-architecture-fails-cloud-independence-requirement.md` — the failure the per-constraint line exists to prevent
- **Locked decisions — do NOT re-open:** D5 (N2 exits by the mapping check; TGC not applicable); the frozen `tests.json` (a criterion you want to change is a double-back to N1, not an option); the chief-pm rulings of 2026-09-07 (`BUILD_LEDGER.md`): `Decision.md` section names are fixed (`## Options` · `## Decision` · `## Architecture` · `## Mapping` · `## Cuts`); tests are `T<n>` by position.
- **Loop state:** node `deciding`; `01_understand/` frozen.

### Your task

Create `<run-dir>/02_decide/Decision.md` with its first two sections.

1. **Header.** `# Decision — <slug>` then one line: run id · node `deciding` · driver · date · `Tests: T1..TN from 01_understand/tests.json (frozen <first 8 of its sha256>)`. Then `## Options`.
2. **Number the tests, then generate.** List `T1..TN` once at the top of `## Options` as `T<n> — <the statement's first clause>` so a reader never opens `tests.json` to follow the section. Then propose **two or three genuinely different approaches** — different shapes, not one approach with a knob. For each `### Option <letter> — <name>`: one paragraph of shape; a **per-test line** for every `T<n>` (`passes` / `passes with <named component>` / `cannot pass — <why>`); a **per-constraint line** for every `## Constraints` entry (`satisfies` / `violates` / `unknown — <what would settle it>`); trade-offs (what it costs, what it forecloses); YAGNI applied — every feature no `T<n>` needs is removed from the option before it is written down. An option with a `violates` on a HARD constraint is struck through and kept in the list with the line that killed it — it is evidence, not an option.
3. **Recommend first.** Open `## Decision` with the recommended option and the reason in one paragraph, then why not each of the others in one line each. The reason names tests and constraints, never taste.
4. **Verify what the choice rests on.** If the recommended option passes a `T<n>` or satisfies a constraint only by assuming a tool, platform or environment behaviour nobody has verified — CALL `assumption-check` (proactive mode) on that assumption and paste its register row under `## Decision`. A `low confidence + load-bearing` row is verified before this file is handed back, or the option is not recommended.
5. **Decide.** If `loop.state.json` says Daniel is present: one question — accept or override, with your recommendation stated — and record his answer verbatim. If absent: the recommendation IS the decision; write `Decided by: <driver>, Daniel absent` so the choice is a ruling on the record. Hand back to the node for step 3.

**Acceptance:** `## Options` lists `T1..TN`; two or three options, each with N per-test lines and one line per constraint; every struck option shows the constraint that struck it; `## Decision` opens with the choice and its reason, names tests and constraints, and says who decided; any assumption the choice rests on has a register row from the `assumption-check` call.

### Out of scope

- The architecture of the chosen option — `demi-decide-architecture-sketch` (step 3). An option paragraph is a shape, not a component list.
- Cutting anything — `demi-decide-ruthless-descoping`. YAGNI here trims a proposal; the two-part rule is applied later, with the principle snapshot open.
- Re-triaging the path or editing `Problem.md` / `tests.json` — frozen; a test you cannot pass under any option is a stop (below), not an edit.
- `## Architecture`, `## Mapping`, `## Cuts` — owned by the sibling demis; do not create the headings.

### Deliverable format

- **Writes:** `<run-dir>/02_decide/Decision.md` (header, `## Options`, `## Decision`).
- **Returns (to the node):** the path · option count (struck count) · the chosen option's letter and one-line reason · assumption rows verified / unverified · who decided — under 60 words.

### Escalate if

- No option passes every `T<n>` without violating a HARD constraint → return to Daniel naming the test and the constraint; do NOT recommend the option that violates least.
- `assumption-check` returns `unverified` on a load-bearing row for the recommended option → stop; name what resolves it; do NOT recommend on the assumption.
- Two options tie and the wrong one is a rebuild → return to Daniel with both and your lean; do NOT pick silently when he is absent.
- Only one option exists after honest generation → say so and why in `## Options`; do NOT pad a second option nobody would build.

## Self-review

- [ ] The options are different shapes, not one shape at two sizes; I can name the test each one handles worst.
- [ ] Every `T<n>` and every `## Constraints` line has a verdict under every option — no option is graded only on the tests it likes.
- [ ] `## Decision` cites `T<n>` ids and constraint lines; "elegant" or "cleaner" does not carry the decision.
- [ ] Placeholder scan: no `TBD`, no `unknown` left unresolved on the chosen option, no assumption row typed from memory.

## Gate contribution

Indirect. `check_deciding` reads `mapping.json`, not this section — nothing mechanical checks `## Options` today. What this demi contributes is the `T<n>` vocabulary (the numbering the mapping's `tests` lists use) and the option the sketch decomposes; a wrong option here produces a mapping that passes the gate and a design that fails the tests at N4. The Self-review is the check for content; for shape, `Decision.md` renders from `_agentOS/skills_library/_meta/templates/loop/decision.template.md` and `python3 $AGENTOS_ROOT/system/bin/template_lint.py --template <t> --document <d>` refuses a missing or out-of-order section and any unfilled `«FILL: …»` marker (landed T4.6, 2026-09-08; not wired into `check_deciding`).

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The architecture obviously satisfies the constraints." | INC014: *"It was not adequately considered when Item 2 architecture was chosen"*; the deployment model was *"treated as a setup detail"*. One line per constraint, per option — the line is cheaper than hour four. |
| "I know which option we'll take; the others are ceremony." | Retrospective F2: the whole architecture *"was designed without the test in view."* A second option graded against `T<n>` is the only thing that shows the first one is not just the one you thought of first. |
| "This option passes the test once we add a criterion for it." | The tests are frozen. A criterion added at N2 is a double-back to N1 (hash-detected) — say so and stop; do not grade an option against a test that does not exist (Law 9: no placeholder inside a gate). |

## Source

- **Parent node:** `gear3-decide`
- **Origin:** Plan T4.4 (2026-08-27); PRD §3.N2; chief-pm rulings 2026-09-07 (`BUILD_LEDGER.md`): `Decision.md` section names; `T<n>` by position; proportionality (bounded inline, architectural may dispatch).
- **Precedent failures:** `m4-loop/gear3-decide-baseline.md` rows 3 (architecture before the test), 5 (placeholder test), 6 (INC014).
- **Authored by:** chief-pm on 2026-09-07.
- **Community lineage:** obra/superpowers `brainstorming` 6.3.0 (MIT), archived at `01_research/upstream-source-6.3.0/skills/brainstorming/SKILL.md` §"Exploring approaches". Ported: propose 2–3 different approaches with trade-offs; lead with the recommended option and the reason; YAGNI ruthlessly on every approach. Not ported: the conversational presentation with per-section approval, the visual companion, the design-doc write and its user-review gate, the writing-plans handoff. Port / no-port table: `m4-loop/DerivationScope_gear3-decide_ChiefPM_2026-09-07.md`.
- **Sibling demi-skills:** `demi-decide-architecture-sketch`, `demi-decide-ruthless-descoping`.
