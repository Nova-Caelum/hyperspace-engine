# Handoff Prompt Template (gear5-build)

Ported from `sprint-manager/references/handoff-prompt-template.md` (internal). Every implementer dispatch in the Build node follows this structure. The brief is written to `<run-dir>/build/<row>/brief.md` **before** the `Agent` call — the saved brief is the audit trail and the implementer's only source of requirements. Subagents have no conversation memory; the anchor docs ARE their context.

---

## Template (paste-ready, substitute bracketed values)

```
## Context

- **Loop run:** [run-dir] · node `executing` (N4 Build) · row `[external_id]`
- **Anchor docs (READ THESE FIRST):**
  - [run-dir]/build/[external_id]/brief.md  ← this file
  - [the row's typed acceptance criteria, quoted verbatim below in Your task]
  - [concrete paths: the code/tests the row touches, the decision entries that bind it]
- **Decisions already locked — do NOT re-open:** [D-numbers]
- **Isolation:** [shared-tree — files: … | worktree] — baseline: [explicit test command]
- **Trigger tokens for your preloaded skills:** [literal tokens, e.g. "TDD", "verification-before-completion"] — conditional skills stay dormant without them
- **Implementer contract:** you do not dispatch subagents; you do not close the row; you do not promote, deploy, or edit runtime paths

## Your task

[One paragraph of goal.] Then numbered imperative steps. Step 1 is always the pre-flight (clean tree, baseline command green or reported red). Then the row's typed acceptance criteria, quoted verbatim, as the acceptance list — exact values (names, paths, strings) appear here and nowhere else.

## Out of scope

- [Files owned by other in-flight rows — name them]
- [What must not change: frozen artifacts, other lanes' files, schemas]
- No promote, no PR, no deploy, no `~/.claude/**` edits, no Task Graph writes, no headless `claude` runs

## Deliverable format

- **Writes:** [concrete paths] + the report file `[run-dir]/build/[external_id]/report.md` — contains the RED run output (test failing for the expected reason), the GREEN run output, the commands run, and concerns
- **Returns (≤150 words):** status `DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED`, files touched, one-line test summary, concerns
- **Worklog:** one `append_worklog` (author = your persona, project = [project code], tags `[run-slug]`, `loop-run`, `[external_id]`; summary ≤280 chars) before returning

## Escalate if

- [Concrete halt condition] → return `BLOCKED` with [what to write to the report]; do NOT [the workaround you must not take]
- A typed criterion cannot be discharged as written → return `NEEDS_CONTEXT` naming it; do NOT reshape the work to fit a broken criterion
- The task needs an irreversible or destructive step, a security-sensitive action, or a side effect outside the workspace → stop and return; the controller rules
```

---

## Quality criteria

- **Self-contained.** A fresh subagent reading only the brief and its anchor docs has everything. No "as we discussed".
- **Concrete paths.** "Write to `<run-dir>/build/<row>/report.md`" — never "document your work".
- **Exact values live in the brief only.** Never in the dispatch message, never in a pasted summary of earlier rows. A real upstream session's dispatch reached 42k characters of which 99% was pasted history.
- **Locked decisions are named.** "Do NOT re-open D11–D13" — not implied.
- **Halt conditions are typed.** Trigger → return status → what not to do meanwhile.
- **Return length is capped.** Subagents return long; say the cap.
- **Anchor docs first.** The block is mandatory and literal — it is what makes the brief mechanically recognizable as dispatchable.
- **Constraint reminders.** "Do NOT promote." "Do NOT touch files owned by row X." "Do NOT add dependencies." Named, not implied.
- **Worklog discipline encoded.** The brief names author, project, tags and the ≤280-char summary cap; the implementer appends before returning, not after being asked.

## What changed from the sprint-manager template

Dropped: phase/variant vocabulary, `sprint-manager-v2-fired` telemetry tags, `DANIEL_INPUT.md` (rulings go to `BUILD_LEDGER.md` and reach Daniel in the node's final "Rulings I made" list), the sprint-folder reference implementations. Added: loop position line, typed-criteria-verbatim rule, the implementer contract, the report-file RED/GREEN requirement, trigger tokens.

## Source

`sprint-manager/references/handoff-prompt-template.md` (Nova Caelum, v2 2026-06-27; itself preserved from v1 2026-04-26) · dispatch discipline from obra/superpowers `subagent-driven-development` 6.3.0 (MIT) §"Dispatch the implementer" · PM-3 trigger-token embedding (chief-pm persona).
