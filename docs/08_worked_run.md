# 08 — A worked run

One goal, start to finish, with the commands that moved it and the artifacts each station produced.

**About the content:** the folder layout, file names, command shapes, gate behaviour and refusal
messages here are taken from the engine's own source and are exact. The *goal* is illustrative — a small
feature, chosen because it is big enough to need all five stations and small enough to read in one
sitting. Where a value would differ in your run, it is written as a placeholder.

---

## The goal

> *"Our status endpoint returns 200 even when the database is unreachable. It should fail honestly."*

Small, real, and the kind of thing an agent will confidently declare fixed while the underlying problem
is untouched — which makes it a useful thing to watch a gate catch.

---

## Station 0 — session entry

The session starts. `acing-hyperspace` fires before anything else, looks for a run for this goal, finds
none, and routes to `gear2-understand`.

Nothing is created yet. Routing happens before the first action, not after it.

---

## Station 1 — Understand

### Opening the run

The verbatim ask is written down first, then the run is opened against it:

```bash
# the ask, exactly as it was given, before anyone paraphrases it
$EDITOR <parent>/honest-status/original_input.md

python3 bin/loop_state.py init \
  --goal honest-status \
  --input <parent>/honest-status/original_input.md \
  --workspace <parent>
```

`init` lays down the run and prints the path to its state file:

```
<parent>/honest-status/loop.state.json
```

The folder now looks like this — and this layout is the engine's, not a convention:

```
honest-status/
├── loop.state.json      Engine state. Never hand-edit.
├── original_input.md    The ask, verbatim. The run's anchor.
├── DRIVE_MAP.md         Generated. Rewritten at every node entry and every gate.
├── handoffs/            Anything written for another session to act on
├── notes/               Anything written to think with
└── misc/                Better here than loose at the root
```

The state file reads `status: framing`, `current_node: framing`. Then the run enters the station:

```bash
python3 bin/loop_state.py set-node honest-status/loop.state.json --node understanding
```

`01_understand/` is created by this station, as each node folder is created by its own gear.

### Writing what "done" means

Two artifacts. `Problem.md` states the problem, the constraints and what is out of scope.
`01_understand/tests.json` holds the acceptance criteria — and this file is the one everything later
measures against.

The criteria for this goal, in shape rather than in full:

| # | Statement | Verification |
|---|---|---|
| T1 | `WHOLE-PATH:` with the database unreachable, a request to `/status` returns a non-2xx and names the failure | `command_check` |
| T2 | With the database reachable, `/status` still returns 200 | `command_check` |
| T3 | The failure path is covered by a test that fails before the fix and passes after | `command_check` |
| T4 | The response body does not leak the connection string | `file_state` |
| T5 | A human confirms the failure message is intelligible to an on-call engineer | `manual` |

Note what makes this set pass its own gate. T5 is the criterion that actually matters to a person — and
on its own it would be refused, because an all-manual set defines a "done" no machine can confirm. T1
through T4 are what make T5 admissible. And T1 carries the `WHOLE-PATH:` prefix, because four passing
units routinely describe a system that is still broken end to end.

### The gate

Dry run first — same verdict, nothing frozen:

```bash
python3 bin/loop_state.py check honest-status/loop.state.json \
  --node understanding --tests honest-status/01_understand/tests.json
```

**First attempt refuses.** T1's statement was written without its prefix:

```
no WHOLE-PATH: criterion — at least one criterion must exercise the whole
path from entry to finish (SystemShape §11.9; PRD C10/C12)
```

One edit, re-run, and the gate reports a count line. Now pass it for real:

```bash
python3 bin/loop_state.py gate-pass honest-status/loop.state.json \
  --node understanding --by <agent> \
  --artifact honest-status/01_understand/Problem.md \
             honest-status/01_understand/tests.json \
  --tests honest-status/01_understand/tests.json
```

Exit 0. Both artifacts are now recorded in `loop.state.json` with their sha256, `gates` gains an entry,
and `DRIVE_MAP.md` is rewritten.

**From here, "done" is fixed.** Editing `tests.json` now is possible and is recorded as a double-back.

---

## Station 2 — Decide

```bash
python3 bin/loop_state.py set-node honest-status/loop.state.json --node deciding
```

`02_decide/` appears. Four artifacts: `Decision.md` (the choice and why), `mapping.json` (tests →
components), `Deferred.md` (what is deliberately not being done), `principles.json` (the snapshot that
justifies components no test demands).

The mapping, in shape:

| Component | Satisfies | Kept by |
|---|---|---|
| `health-probe` — an actual connectivity check rather than a constant | T1, T2 | tests |
| `error-shape` — a failure body that names the subsystem and leaks nothing | T4, T5 | tests |
| `regression-test` — the failing-before, passing-after case | T3 | tests |

`Deferred.md` names, by exact component name, the thing considered and cut: a retry-with-backoff layer.
Cutting is fine. Cutting silently is what the gate prevents.

### The gate

```bash
python3 bin/loop_state.py check honest-status/loop.state.json \
  --node deciding --decision honest-status/02_decide/mapping.json
```

**Refuses, with two causes at once** — the gate collects rather than stopping at the first:

```
T5 maps to no component
error-shape: unknown test id T6 (tests.json declares T1..T5)
```

Both from the same slip: T5 was typed as T6. This is the gate doing its most valuable work — a design
that read as complete and quietly did not address the criterion a human cares about most.

Fix both, re-run, pass:

```bash
python3 bin/loop_state.py gate-pass honest-status/loop.state.json \
  --node deciding --by <agent> \
  --artifact honest-status/02_decide/Decision.md \
             honest-status/02_decide/mapping.json \
             honest-status/02_decide/Deferred.md \
             honest-status/02_decide/principles.json \
  --decision honest-status/02_decide/mapping.json
```

Exit 0. Four more artifacts frozen.

---

## Station 3 — Draft

```bash
python3 bin/loop_state.py set-node honest-status/loop.state.json --node specifying
```

`03_draft/` appears: `PRD.md`, `Plan.md`, `workplan.json`, and the component list.

`Plan.md` carries one level-4 block per task:

```markdown
#### T1.1 — Replace the constant health check with a real connectivity probe
task_id:
...

#### T1.2 — Shape the failure response; assert no connection string in the body
task_id:
...

#### T1.3 — Add the failing-before / passing-after regression case
task_id:
...
```

The `task_id` fields are blank on purpose. **The filing step writes them.**

Filing happens, each row lands on the tracker, and the ids are backfilled into the plan.

### The gate

```bash
python3 bin/loop_state.py check honest-status/loop.state.json \
  --node specifying --plan honest-status/03_draft/Plan.md
```

**Refuses on one block:**

```
T1.3: task_id is blank — not backfilled by the uploader
```

The third row never filed. The plan looked finished and was, in the only sense the engine cares about,
two-thirds filed.

The temptation here is to type a UUID into the field. That passes the gate and destroys the only proof
the engine has that the work exists as a trackable row. File the row instead; let the uploader write the
id. Then:

```bash
python3 bin/loop_state.py gate-pass honest-status/loop.state.json \
  --node specifying --by <agent> \
  --artifact honest-status/03_draft/PRD.md honest-status/03_draft/Plan.md \
  --plan honest-status/03_draft/Plan.md
```

Exit 0.

---

## Station 4 — Build

```bash
python3 bin/loop_state.py set-node honest-status/loop.state.json --node executing
```

`build/` appears, one subfolder per row. `BUILD_LEDGER.md` at the run root gets one line per row.

Work happens. Each row is closed through the verifier, which writes a run file per attempt into the
verifications directory. `RECONCILIATION.md` gives every row a disposition:

| Row | Disposition | Why |
|---|---|---|
| T1.1 | `done` | Built, verifier closed it |
| T1.2 | `done` | Built, verifier closed it |
| T1.3 | `done` | Built, verifier closed it |
| *(deferred retry layer)* | `deferred` | Descoped at Decide. Never built, so nothing to verify. |

### The gate, and a HOLD

```bash
python3 bin/loop_state.py gate-pass honest-status/loop.state.json \
  --node executing --by <agent> \
  --artifact honest-status/BUILD_LEDGER.md honest-status/RECONCILIATION.md \
  --workplan honest-status/03_draft/workplan.json \
  --reconciliation honest-status/RECONCILIATION.md \
  --verifications-dir honest-status/build/_verifications
```

**Exit 3 — HOLD.** T1.2's verifier status came back `unverifiable`, because one of its criteria is T5:

```
<row-id-for-T1.2>: manual criterion undischarged —
  "A human confirms the failure message is intelligible to an on-call engineer"
```

This is not a failure. The work is built. The gate has enumerated exactly what to ask, and that list is
the agent's agenda with the human.

There are two wrong moves available and both pass the gate. Reclassifying T1.2 to `deferred` — it was
built, so that is false. Or removing T5 from the criteria — which is editing the definition of done after
seeing the result, and is recorded as a double-back against frozen artifacts.

The right move is to ask. The human reads the failure message, says whether an on-call engineer would
understand it, and that attestation discharges the criterion. Re-run the gate:

```
exit 0
```

**The Build gate confers `status: live`** and leaves `current_node: executing` untouched. The run is
built. The agent is no longer permitted to build.

---

## Station 5 — Live

Nothing is built here.

The agent announces the run is live and hands over the acceptance test **as written at station one** —
T1 through T5, unchanged. Not a test invented now to match what got built; the whole value of freezing
the criteria at the start is that this handover cannot be renegotiated at the end.

The human runs it. Unplugs the database, hits the endpoint, reads the failure, plugs it back in, checks
200 returns.

It passes, with one wrinkle: the failure names the subsystem correctly but takes eleven seconds to
return, because nothing bounds the connection timeout. Nobody wrote a criterion about latency.

That is an **escape** — a defect the human's test caught that the run's own tests missed. It gets
recorded:

```bash
python3 bin/loop_state.py confirm honest-status/loop.state.json \
  --by <human> --escaped 1 --caught 0
```

`status: done`. `final_route: done`. `escape_rate` written.

`confirm` requires human authority on the driver record. No agent can reach this line.

---

## What the state file says afterwards

```
current_node : executing          never advanced past the build
status       : done
final_route  : done
gates        : 4 passed
artifacts    : 8 frozen, with hashes
escape_rate  : 1 escaped, 0 caught
double_backs : 0
```

Read `current_node: executing` next to `status: done` and the design is visible in one line. The node
track went flat; the status track finished. The agent never judged itself complete — the gate withdrew
its permission to build, and a human supplied the verdict.

---

## What this run teaches

**Three of the four gates refused on the first attempt.** A missing `WHOLE-PATH:` prefix, a mistyped
test id that silently orphaned the criterion a human cared about most, and a row that was never filed.
None would have been caught by review; all three would have shipped as "done".

**The HOLD was the most useful moment in the run.** Not a blockage — a built feature and a precise
question, surfaced at the point where asking was cheap.

**The escape is the most valuable output.** One defect reached the human because nobody wrote a
criterion about latency. That is a finding about the criteria, not about the code, and it is the kind of
finding that makes the next run's station one better. `escape_rate` exists to make it countable.

---

| | |
|---|---|
| **The stations in detail** | [`02_the_loop_and_gates.md`](02_the_loop_and_gates.md) |
| **Why it is shaped this way** | [`05_design_rationale.md`](05_design_rationale.md) |
| **When a gate refuses you** | [`07_troubleshooting.md`](07_troubleshooting.md) |
