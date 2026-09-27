# 02 — The loop and its gates

Five stations. Four gates. This file takes them one at a time: what each station is for, what it
consumes, what it produces, and exactly what its gate checks before it will let the run past.

Terms used here without explanation are defined in [`01_introduction.md`](01_introduction.md).

Exact flags, field names and exit codes are in [`reference/`](reference/), which is generated from
source. This file describes behaviour; `reference/` quotes it.

---

## The shape of the whole thing

```
            ┌─ acing-hyperspace ─┐   session entry, every time
            │   routes the work  │   (not a station)
            └─────────┬──────────┘
                      ▼
  framing ──▶ understanding ──▶ deciding ──▶ specifying ──▶ executing ──▶ (stage)
              gear2-understand  gear3-decide  gear4-draft    gear5-build    gear6-live
                    GATE           GATE          GATE           GATE        no gate
                      │              │             │              │
                   frozen         frozen        frozen         frozen
                 tests.json    mapping.json    Plan.md     reconciliation
                                                              │
                                              status: live ◀──┘
                                                              │
                                        human's acceptance test
                                                              │
                                              status: done ◀──┘  (human only)
```

Read the bottom-right corner carefully. `current_node` stops at `executing`. The two steps after it
are moves on the `status` axis, and the last one is not available to an agent at all.

---

## Station 1 — `gear2-understand` · node `understanding`

**Entered when** a goal arrives that nobody has framed. There is no run yet, or the run reads
`framing`.

**The job.** Decide what "done" means, and freeze it before a line is built. This is the station that
makes the rest of the loop possible: every later gate measures against the criteria written here, so
criteria written loosely here produce a loop that cannot catch anything.

**Produces** `tests.json` — a set of acceptance criteria, each with a typed verification — plus the
problem statement that motivates them.

### What the gate checks

`tests.json` must be a valid work-item envelope, and the validation run *is* the evidence. In order:

1. **Readable and JSON and an object.** Otherwise refused, naming the file.
2. **Valid against the `CandidateWorkItem` contract.** The contract is imported lazily from the plugin
   rather than vendored into a second copy — a vendored copy is a copy that drifts. An import failure or a validation error is
   refused *with the validator's own text*, not a paraphrase.
3. **At least one non-`manual` criterion.** An all-manual test set is refused by name:

   > `C10: no machine-checkable criterion — an all-manual test set cannot pass its own N1 gate`

   The reasoning: a criterion only a human can judge cannot discharge itself, so a set made entirely
   of them defines a "done" that the machine can never confirm. Keep the human judgment criteria —
   just put an executable one beside them.
4. **At least one `WHOLE-PATH:` criterion.** One criterion must exercise the whole path from entry to
   finish:

   > `no WHOLE-PATH: criterion — at least one criterion must exercise the whole path from entry to finish`

   This exists because a test set of individually-passing units routinely describes a system that
   does not work end to end. Something has to assert the seam.

**No hold path.** This gate passes or refuses. There is nothing here a human is expected to supply
mid-check.

---

## Station 2 — `gear3-decide` · node `deciding`

**Entered when** the tests are frozen and the design is still open.

**The job.** Choose how to build it, and prove the choice covers the criteria. Not "sketch an
architecture" — *map every frozen test to something that will satisfy it.*

**Produces** `mapping.json` (tests → components), a decision document, a deferred list, and a
principles snapshot.

### What the gate checks

Reading raw JSON and markdown only — no contract import, no network:

1. **Every frozen test maps to a named component.** An unmapped test id is a refusal. This is the
   check that catches the most common design failure: a design that is coherent and quietly does not
   address one of the things you said mattered.
2. **Every component is justified.** Each one is kept either by a test it satisfies or by a declared,
   citable principle. A component that appears for neither reason is scope nobody asked for.
3. **Everything else is explicitly deferred.** Anything not kept must be bulleted under `## Deferred`
   in the deferred-list document. Cutting is fine; cutting silently is not.

**Refusals are staged, deliberately.** The gate does not stop at the first problem. It resolves as
far as it can and collects every cause at that level: first the mapping's missing keys, all of them;
then the referenced files, all of them; then every component-level cause and every unmapped test id
together. One pass, one fix, one re-run — rather than six rounds of discovering one more thing.

**No hold path.**

---

## Station 3 — `gear4-draft` · node `specifying`

**Entered when** the decision is frozen and nothing has been filed.

**The job.** Write the PRD and the plan, then file the work as trackable rows. This is the station
where intent becomes a set of things that can be individually closed.

**Produces** a PRD, and `Plan.md` containing task blocks whose `task_id`s have been backfilled by the
filing step.

**Where rows are filed.** Filing writes one row per task block into the project's own task store — a
local SQLite database at `.hyperspace/graph.db`, reached through the plugin's `hyperspace` MCP server —
and writes the returned row id back into the plan. Nothing leaves the machine. The human-facing view
over the same store is the task-graph console, served locally by `hyperspace serve`.

### What the gate checks

`Plan.md` is read as *text*, through the one task-block parser, imported lazily. No contract, no
network, and deliberately **no lint rule** — a lint is the plan author's self-check, not proof that
anything was filed.

1. **Readable.** Otherwise refused.
2. **At least one task block.** Zero blocks is refused — a plan with no tasks has filed nothing.
3. **Every `#### T<n>.<m>` block carries a non-blank, UUID-shaped `task_id`.**

That third check is the whole point of this gate, and it is more subtle than it looks. The filing step
writes the ids back into the plan. So a blank `task_id` is not a formatting problem — **it is a row
that was never actually filed.** The gate is not checking that the plan is well-written. It is
checking that the plan's claim to have filed work is true.

Every per-block cause — marker absent, value blank, value not a UUID — is collected in document order
so one pass fixes them all.

**No hold path.**

---

## Station 4 — `gear5-build` · node `executing`

**Entered when** rows are filed and software is owed.

**The job.** Build it. Then account for every row you filed.

**Produces** working software, a `BUILD_LEDGER.md` tracking the rows, verifier run files under
`<run>/misc/verifications/`, and a reconciliation artifact giving every row a disposition.

Rows are closed by the verifier, which runs locally and writes one run file per attempt. A row may also
be closed by hand in the task-graph console — a deliberate human closure is a legitimate discharge, and
the two doors are distinguishable afterwards because each writes its own closure label.

### What the gate checks

This is the most substantial gate, and the only one with a HOLD path.

**Every filed row must carry a disposition** in the reconciliation artifact — one of `done`,
`deferred`, `archived`, or `live-test`. **A row absent from the artifact refuses outright.** That
absence is the exact hole this gate exists to close: a row that looked done and was never closed at
all. Silence about a row is the failure mode, so silence is not permitted.

The dispositions are not interchangeable:

| Disposition | Verifier check | Reasoning |
|---|---|---|
| `done` | **Yes** — the row's verifier run file must read `done` | It was built; prove it landed |
| `deferred` | No | Descoped, not built — there is nothing to verify |
| `archived` | No | Same |
| `live-test` | No | Its work cannot begin until the run is live. The only disposition that may cross the gate open. |

**The reconciliation artifact cannot rescue a `done` row.** If a row claims `done` and its verifier
run says otherwise, the row refuses or holds exactly as it would have anyway. Every undischarged
executable criterion — `command_check`, `file_state`, `db_readback`, `http_readback` — still counts,
whatever the reconciliation claims. Writing `done` next to a row is not a way to close it.

**An unreadable verification file is a refusal,** not a skipped row. A check that cannot read its
evidence has not passed.

### HOLD — exit 3

When a `done` row's verifier status is `unverifiable` *and* its verdicts carry an undischarged or
failed `manual` criterion, the gate enumerates that criterion's exact statement.

If every non-passing row is in that state — and none is missing or outright refused — the result is
**HOLD**, exit 3, rather than a refusal. The message names each row and quotes its criterion.

**That list is the agent's agenda with the human.** It is not an error to route around. It is the
gate saying: you built something, a human has to look at it, and here is precisely what to ask them.

The reversal behind this is in [`05_design_rationale.md`](05_design_rationale.md) — an earlier version
let manual criteria defer, and that was undone deliberately.

### On passing

Exit 0 freezes the artifacts and **confers `status: live`**, leaving `current_node: executing`
untouched. The agent is now in a state where it is no longer permitted to build.

---

## Station 5 — `gear6-live` · a stage, no gate

**Entered when** the Build gate has conferred `live`.

**The job.** Stop. Hand over. Watch.

Nothing is built here. The agent announces the run is live, hands the human the acceptance test that
was designed at the very first station — not one invented now to match what got built — and waits.

`gate-pass --node live` is refused outright. The registry of gated nodes contains four entries and
this is not one of them, which is the mechanical expression of "this is a stage, not a gate."

**The exit is the human's verdict.** `confirm` moves `status: live → done`, writes `escape_rate` and
`final_route`, and requires human authority on the driver record. A clean pass with no troubleshooting
is the highest grade available — not because troubleshooting is shameful, but because every
intervention the human had to make is a thing the criteria at station 1 should have caught and didn't.

That is what `escape_rate` records, and it is the only number in the system that scores the loop
rather than the work.

---

## Why the order cannot be rearranged

Each station consumes the frozen output of the one before it. The dependency is not stylistic:

- The Decide gate checks tests → components. Without frozen tests there is nothing to map.
- The Draft gate checks that rows were filed. Without a decision there is nothing to file.
- The Build gate reconciles against filed rows. Without filed rows there is nothing to reconcile.

Skipping a station does not save the work; it removes the evidence the next gate reads. The loop is
one-way because the evidence chain is one-way.

---

| | |
|---|---|
| **Next** | [`03_architecture.md`](03_architecture.md) — what is where in this repository |
| **Skills and actions** | [`04_skills_and_actions.md`](04_skills_and_actions.md) |
| **When a gate refuses** | [`07_troubleshooting.md`](07_troubleshooting.md) |
