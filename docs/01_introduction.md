# 01 — Introduction, concepts and glossary

This file assumes nothing. It explains what the engine is made of, names every term the rest of the
documentation uses, and ends in a glossary you can jump to directly.

If you have not read [`00_start_here.md`](00_start_here.md), start there — it is shorter and it sets
the precedence rule that governs everything here.

---

## 1. The problem, stated precisely

An agent asked to build something will, reliably and without malice, do all of the following:

- declare a stub complete because it has the right shape
- mark a task done because the code it just wrote looks like code that would work
- lose track of what "done" meant, because the definition was never written down before the building
  started and has since been quietly renegotiated in the agent's own favour
- grind for an hour at the end of a build inside a loop it cannot detect, because detecting it would
  require an outside view of its own progress

These look like four problems. They are one. In each case the agent is both the worker and the judge
of the work, and the judgment drifts toward the answer that lets it stop.

The engine's response is structural rather than instructional. It does not tell the agent to be more
careful. It removes the agent's ability to render the verdict:

- **"Done" is defined first and frozen.** The acceptance criteria are written at the very first
  station, hashed, and cannot be edited afterwards without the change being recorded.
- **Progress is a state file, not a belief.** Where the run is, is a fact on disk.
- **Advancement requires evidence, checked by code.** A gate reads specific files and refuses when
  they are absent or malformed. It has no opinion about quality.
- **Finishing is a human capability.** No code path lets an agent move a run to `done`.

---

## 2. Anatomy

### The run

A **run** is one goal moving through the loop. It owns a folder and a state file, and it is the unit
everything else attaches to. Two runs never share a state file.

A run is opened by `loop_state.py init` against a **goal slug** — a short name that becomes the run's
directory name. The slug is the run's identity; re-using one is how you accidentally destroy a run's
history, which is why `init` refuses an occupied slug.

### The state file

`loop.state.json` sits at the run's root and is the answer to "where are we?". It records:

- **identity** — `run_id`, `goal_slug`, the verbatim `original_input` and its hash
- **position** — `current_node`, `status`
- **history** — `trail` (every node entered and exited, with outcomes), `gates` (every gate passed)
- **evidence** — `artifacts`, each with the sha256 it was frozen at
- **cost** — `budget`, the counters described in §6
- **authority** — `driver`, who was at the wheel
- **ending** — `final_route`, `descope_decision_ref`, `kill`, `escape_rate`

It is written exclusively by event verbs in the CLI, each of which enforces its own preconditions.
Hand-editing it produces a file that looks valid and lies — the preconditions were the point.

### The run folder

Alongside the state file, a run accumulates the artifacts each station produces, in a fixed layout so
a stranger can find anything. `drive_map.py` maintains a generated `DRIVE_MAP.md` at the run root,
rewritten at every node entry and every gate, so the folder always carries its own index.

### Nodes and stages

A **node** is a position in the state machine. A **stage** is a phase of work. Most of the time they
coincide — but not always, and the exception is load-bearing:

> Four nodes have gates. The fifth station has no gate, because nothing is built there. It is a
> stage, not a gated node.

`gate-pass --node live` is refused outright. The registry of gated nodes in `bin/node_gates.py`
contains exactly four entries and nothing else.

### Skills, and why their names differ from the node names

Each station is a **skill** — a directory with a `SKILL.md` that the agent loads when it enters that
station. The skill is the only door in.

The skill names and the node names are not the same words, and this is the single most common source
of confusion when reading the state file next to the skills:

| Skill (the door) | Node in the state file | What the station is for |
|---|---|---|
| `acing-hyperspace` | *(none — it routes)* | Session entry. Reads the run and sends the agent to the right station. |
| `gear2-understand` | `understanding` | Define and freeze what "done" means. |
| `gear3-decide` | `deciding` | Choose the design; map every acceptance test to a component. |
| `gear4-draft` | `specifying` | Write the PRD and plan; file the work as trackable rows. |
| `gear5-build` | `executing` | Build the software; reconcile every filed row. |
| `gear6-live` | *(none — confers `live`)* | Hand over to the human. Nothing is built here. |

There is no `gear1`. `acing-hyperspace` occupies the entry position that a `gear1` would have, and
the numbering was not renormalised when that settled.

`framing` is a real status — the state a run is initialised into, which `gear2-understand` is entered
*from*, not the name of a station.

### Demi-skills

Behind each node's `SKILL.md` are **demi-skills**: documents covering one step of that station in
depth. They are not independently invocable. The node is the door; the demis are steps inside the
room.

This matters more than it sounds. An agent handed eleven flat, equally-reachable skills will pick the
wrong one or none. Nesting the steps behind a single entrance removes the choice.

---

## 3. The two axes

`current_node` and `status` are separate tracks, and the separation is the centre of the design.

The naive model — one pointer that advances through the stages and lands on `done` — cannot express
the state that actually matters: **built, and awaiting a human's verdict.** So there are two tracks.

Through the first four stations they move together. Then:

- Passing the Build gate sets `status: live` and **leaves `current_node: executing` untouched.**
- `confirm` moves `status: live → done`, writes `escape_rate` and `final_route`, and **also leaves
  `current_node` alone.**

So `current_node` never advances past `executing`. The node track goes flat while the status track
keeps moving.

That is what allows a build to *end*. The agent arrives at a state where it is no longer permitted to
build, without ever having had to judge that it was finished. The permission was withdrawn by the
gate, not surrendered by the agent.

And `confirm` requires human authority on the `driver` record. There is no route around it.

---

## 4. What a gate actually does

A gate is a function keyed to a node. Running it does three things, in order:

1. **Check.** Read the specific evidence that node owes and verify it exists and parses. Not whether
   it is good — whether it is *there*, and whether it is internally consistent. Examples: the tests
   file validates against the live contract; every acceptance test id is referenced by at least one
   component; every filed row appears in the reconciliation.
2. **Freeze.** Record each named artifact with its sha256 in the state file.
3. **Record.** Append to `gates` and `trail`.

A gate has four possible exits:

| Exit | Meaning |
|---|---|
| `0` | Passed. Artifacts frozen. The Build gate additionally confers `status: live`. |
| `1` | **Refused.** Evidence is missing, inconsistent, or unreadable. The message says which. |
| `2` | **Usage.** An unregistered node, or a required evidence flag not supplied. Your command was wrong, not your work. |
| `3` | **HOLD.** Build only. A row carries an undischarged manual criterion. |

### HOLD, and the decision it reversed

HOLD exists only at the Build gate. The other three checks state explicitly that they have no hold
path: they pass or they refuse.

A **manual criterion** is one only a human can discharge — *"Daniel confirms the page loads"*. An
early version of the loop let those defer: build finishes, the manual criteria carry forward to the
human's stage, the gate passes. That was reversed, and the reasoning is worth holding onto because it
inverts the obvious framing:

> *"If a criterion requires manual verification, and that row is left unclosed, that is a failure on
> the agent to not adequately direct me that they had completed work that was ready to be reviewed."*

An unreviewed row is not a blocked row. It is the agent failing to ask. So HOLD names every affected
row and quotes its criterion, and that list is the agent's agenda with the human — not an error to
work around.

### Freezing, and double-backs

Frozen means hashed, not locked. You can still edit a frozen artifact; the file system does not stop
you. What happens is that the next re-hash notices, and the mismatch is recorded as a **double-back**
on the run.

A double-back is a **quality signal, not a gate failure.** It does not block anything. It accumulates
into the record of how the run actually went — a run with sixteen double-backs at the first station
was not a clean run, whatever its eventual outcome, and the state file says so permanently.

---

## 5. Evidence

"Evidence-bearing" is a specific claim, not a slogan. Two rules give it teeth.

**Evidence is checked, not asserted.** A gate reads files. An agent's sentence about having done
something is not evidence; the artifact is.

**Evidence is a delta.** This is the sharper rule, and it comes from the verifier that closes
individual rows: *a criterion that was already satisfied before the work started does not discharge
it, ever.* Without that rule an agent can close a row by pointing at something that was already true
— technically accurate, entirely worthless. Landing checks compare against the state at filing time.

The verifier returns exactly one of four answers — `done`, `refused`, `unverifiable`, `already_done`.
Never a receipt, never a promise, never "probably". `unverifiable` is a real outcome and routes to a
human rather than pretending to a verdict.

---

## 6. Budgets

A run carries counters for the things that actually cost a human something:

| Counter | Default cap | How it is known |
|---|---|---|
| `fresh_sessions` | 1 | detected automatically at session start |
| `compactions` | 1 | detected automatically |
| `daniel_hours` | 2 | not detected — recorded by hand if at all |
| `worklog_entries` | 3 | not detected |

Two properties matter. **Crossing a cap notifies; it never blocks.** A budget is a signal that this
run is costing more than expected, not a guillotine. And each counter is explicitly flagged as
*detected* or not, so a reader can tell which numbers are real and which are aspirational — a cap
nothing increments is not a measurement.

The counters freeze when a run ends.

The `daniel_hours` name is a genuine artifact of where this came from: the engine was built for one
operator and published with the personalisation intact. Treat it as "human hours".

---

## 7. Quality signals

Separate from gates, a run accumulates a record of how it went:

- **`double_back_rounds`** — frozen artifacts re-hashed to different values. Rework after the freeze.
- **`escape_rate`** — written at `confirm`. Defects the human's acceptance test caught that the run's
  own tests missed, against defects the run's tests caught first. This is the only number that scores
  the loop itself rather than the work: a high escape rate means the acceptance criteria written at
  the first station were not the right criteria.
- **`rework_rounds`**, **`stage_retries`** — re-entries and repeats.

None of these block anything. They exist so that a clean run and a run that thrashed are
distinguishable afterwards, which is the only way the loop's own design can be evaluated.

---

## 8. How a run ends

The full status vocabulary lives in `bin/loop_terminal.py`:

```
framing · understanding · deciding · specifying · executing · verifying
live · done · descoped · killed · abandoned_budget · blocked_external
```

Three of these are **legitimate endings**:

| Ending | Means |
|---|---|
| `done` | The human ran the acceptance test and it passed. Requires human authority. |
| `descoped` | A decision was recorded to stop. The work was cut deliberately, and the decision is referenced from the state file — *"the decision is recorded, not remembered."* |
| `killed` | The kill path fired. |

Two statuses are **kill triggers** rather than endings in themselves — `abandoned_budget` and
`blocked_external`. They route to `killed`. The reasoning: a run that quietly dies of budget
exhaustion is the same failure as a row that quietly never gets filed. Both must resolve to a named
outcome rather than sitting unresolved forever.

`live` is deliberately **not** terminal. It means built and awaiting the human.

`verifying` is in the vocabulary with no gate registered against it. It is unused. It was left in
rather than quietly removed, because a vocabulary that silently loses a value is harder to trust than
one that admits a spare.

Ending is derived, not declared. A predicate reads the state and returns the route; it takes no
outcome argument from any caller, so no agent can request an ending. It is also cause-blind: it reads
whether a kill fired, not why. The why is recorded elsewhere, for a human.

---

## 9. Glossary

**acing-hyperspace** — The session-entry skill. Runs at every session start (cold, resumed, cleared,
compacted) and routes the work to the station it belongs in. Not a station itself.

**Acceptance criterion** — A statement of what must be true for a row to be done, paired with a typed
verification. Written before the building starts. See *manual criterion*.

**Budget** — Per-run counters for human-facing cost. Notify on crossing; never block. §6.

**Demi-skill** — A document behind a node's `SKILL.md` covering one step in depth. Not independently
invocable.

**Double-back** — A frozen artifact re-hashed to a different value. A quality signal, not a failure.

**Driver** — The record of who held authority at a decision point. `confirm` requires a human driver.

**Escape rate** — Written at `confirm`. Defects the human caught that the run's own tests missed. The
number that scores the loop rather than the work.

**Evidence** — Files a gate reads. Distinct from claims an agent makes. Must be a *delta* — something
that became true through the work.

**final_route** — The derived ending of a run: `done`, `descoped`, `killed`, or none yet. Derived by a
predicate from state, never supplied by a caller.

**framing** — The status a run is initialised into. `gear2-understand` is entered *from* it. Not a
station.

**Freeze** — Record an artifact's sha256 in the state file at a gate. Does not make the file
read-only; a later mismatch is a double-back.

**Gate** — The exit check on a node. Reads evidence, freezes artifacts, records the pass. Exits 0, 1,
2, or 3. Has no opinion about quality.

**Goal slug** — A run's short name and its directory name. Its identity. Re-using one is how a run's
history gets destroyed, which is why `init` refuses an occupied slug.

**HOLD** — Exit 3. Build gate only. An undischarged manual criterion on a row. Names every affected
row and quotes its criterion. The agent's agenda with the human, not an error.

**Manual criterion** — An acceptance criterion only a human can discharge. Holds the Build gate; see
§4 for the decision that reversed.

**Node** — A position in the state machine. Four are gated. Named differently from the skill that
enters them; see the mapping table in §2.

**Run** — One goal moving through the loop. Owns a folder and a state file.

**Stage** — A phase of work. Coincides with a node except at the fifth station, which is a stage with
no gate.

**status** — One of two position axes. Tracks how far the run has got toward an ending, and keeps
moving after `current_node` goes flat. §3.

**current_node** — The other axis. Never advances past `executing`. §3.

**Trail** — The state file's record of every node entered and exited, with outcomes.

**Verifier** — The component that closes an individual row on evidence. Five steps; returns exactly
one of `done`, `refused`, `unverifiable`, `already_done`.

**verifying** — A status in the vocabulary with no gate registered. Unused, and left in deliberately.

---

| | |
|---|---|
| **Next** | [`02_the_loop_and_gates.md`](02_the_loop_and_gates.md) — the stations in detail |
| **Why it is shaped this way** | [`05_design_rationale.md`](05_design_rationale.md) |
| **Exact field names and exit codes** | [`reference/`](reference/) — generated from source |
