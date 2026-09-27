# 04 — Skills and actions

Everything the engine can be told to do, in two halves: **what you need to know** and **what the agent
needs to know.**

Those are different lists. Most documentation blends them and serves neither — a human wading through
state-machine verbs they will never type, an agent reading advice aimed at a person. Here they are kept
apart.

Exact flags and arguments are in [`reference/`](reference/), generated from source. This file says what
each thing is *for*.

---

## The skills

Six. Five are stations; one is the way in.

| Skill | Fires when | Owns |
|---|---|---|
| `acing-hyperspace` | **Every session start** — cold, resumed, cleared, compacted | Routing. Reads the run's state and sends the agent to the station it belongs in. Not a station itself. |
| `gear2-understand` | A goal arrives unframed | Defining and freezing what "done" means |
| `gear3-decide` | Tests frozen, design open | Choosing the design; mapping every test to a component |
| `gear4-draft` | Decision frozen, nothing filed | The PRD and plan; filing the work as trackable rows |
| `gear5-build` | Rows filed, software owed | Building it; reconciling every filed row |
| `gear6-live` | Build gate has conferred `live` | Handing over. Nothing is built here. |

**Each skill is the only door into its station.** Not the preferred route — the only one. The gate
contracts assume the artifacts that station produces, so entering the work without entering the skill
produces a run that cannot pass its own gate.

### `acing-hyperspace` deserves its own paragraph

It is the only skill that fires unconditionally. Its job is to make the routing decision *before the
agent's first action* — including before a clarifying question, a file read, or a plan.

That timing is the whole mechanism. A routing check that fires after the agent has begun is a check the
agent has already routed around, because it started work in whatever frame the conversation happened to
be in. The run's state file, not the conversation, decides where a resumed session re-enters.

### Demi-skills

Behind each station's `SKILL.md` are demi-skills: documents covering one step of that station in depth.
**They are not independently invocable.** The node is the door; the demis are steps inside the room.

This is a deliberate structural choice, not filing tidiness. An agent handed eleven flat,
equally-reachable skills picks the wrong one or none at all. Nesting the steps behind one entrance
removes the choice, so the only decision left is *which station am I in* — which the state file already
answers.

---

## The actions

Four executables. `loop_state.py` carries the state machine and most of the surface.

### Run lifecycle

| Action | For |
|---|---|
| `init` | Open a run. Creates the run folder, the state file, the skeleton layout, and the first drive map. Takes the goal slug and the verbatim original input. |
| `read` | Print the state file. The safe way to ask "where are we?" |
| `set-node` | Record a stage-boundary transition. Mirrors into `status` for the four stage nodes; refuses to downgrade a run that has already ended. |

### Gates

| Action | For |
|---|---|
| `gate-pass` | Run a node's exit check and, on pass, freeze its artifacts and record the pass. The Build gate additionally confers `status: live`. Exits 0, 1, 2, or 3. |
| `check` | Run the same check **without** freezing or recording. The dry run. |

`check` before `gate-pass` costs nothing and tells you the same thing. Use it.

### Endings

| Action | For |
|---|---|
| `confirm` | Move `status: live → done`. Writes `escape_rate` and `final_route`. **Requires human authority on the driver record.** |
| `descope` | Record a deliberate decision to stop. Takes a reference to where the decision is written — *the decision is recorded, not remembered.* |
| `record-kill` | Fire the kill path. The cause is recorded for a human and never gates the route. |

### Records and signals

| Action | For |
|---|---|
| `record-approval` | Record who held authority at a decision point — tier, whether a human was present, who could drive. |
| `bump` | Increment a detected budget counter for one session-start event. Self-gates on a terminal run: an ended run's counters are frozen. |
| `notify` | Print one line per crossed budget cap. **Never blocks.** Exits 0 always. |

### The run folder and the plan

| Action | For |
|---|---|
| `drive_map.py write <run_dir>` | Regenerate `DRIVE_MAP.md`. Called automatically at every node entry and every gate. |
| `drive_map.py check <run_dir>` | Report stray files — anything in the run folder the schema does not place. |
| `plan_lint.py <plan>` | Lint a plan's markdown. **A self-check, not a gate** — the Draft gate deliberately applies no lint rule. |

---

## What the user needs to know

If you are driving, this is your list. Everything above that is not here, the agent handles.

**1. You define "done", and it is frozen before anything is built.**
The highest-leverage thing you do. Every gate measures against the criteria written at the first
station. Loose criteria produce a loop that runs beautifully and catches nothing — and you will only
find out at your own acceptance test. Two rules the gate enforces: at least one criterion a machine can
check, and at least one that exercises the whole path end to end.

**2. Only you can finish a run.**
`confirm` requires human authority. There is no code path by which an agent promotes its own work to
`done`. This is the point of the whole system, and it means a run will sit at `live` indefinitely until
you look at it. That is correct behaviour, not a stall.

**3. HOLD means the agent is asking you something.**
Exit 3 with a list of rows and quoted criteria is not a failure. It is built work waiting on your
judgment, with the exact questions enumerated. Working through that list is the fastest path to `done`.

**4. Budgets tell you when a run is costing more than expected.**
Crossing a cap notifies; it never blocks. Two counters are detected automatically; two are recorded by
hand. Treat a crossed cap as a prompt to ask whether the run is still worth its cost.

**5. A double-back is information, not a scolding.**
Frozen artifacts that change are recorded. A run with many double-backs at the first station was a run
whose definition of done kept moving — worth knowing afterwards, whatever the outcome.

**6. `escape_rate` scores the loop, not the work.**
Written when you confirm. Defects your acceptance test caught that the run's own tests missed. A high
number means the criteria at station one were the wrong criteria — which is a fixable, structural
finding, and the most useful number the system produces.

**7. Ceremony scales; gates do not.**
A one-line fix does not need a PRD. Compress the artifacts freely. Do not skip the evidence, because
the evidence is what the next station reads.

---

## What the agent needs to know

**1. The state file is the authority on where you are.** Not the conversation, not your memory of it,
not what the last message was about. A resumed or compacted session re-enters at the node the state file
names. Read it before acting.

**2. Never hand-edit the state file.** Every write goes through an event verb that enforces
preconditions — and the preconditions are the point. A hand-edited state file looks valid and lies.

**3. Enter through the skill, every time.** The station's skill is the only door. Starting the work
without entering the skill produces artifacts the gate will not recognise, and you will discover this at
the gate rather than at the start.

**4. Run `check` before `gate-pass`.** Same verdict, no freeze, no record. There is no reason not to.

**5. Read every line of a refusal.** Gates collect all causes at a level. Fixing the first of six and
re-running wastes a round, and rounds are the budgeted resource.

**6. Distinguish exit 1 from exit 2.** Exit 2 means your command was wrong. Exit 1 means your work is
not finished. Re-running with different flags cannot resolve an exit 1.

**7. Never satisfy a check by hand.** Hand-writing a `task_id`, reclassifying a row to a disposition the
verifier does not check, editing a frozen artifact to match a hash — each of these passes a gate while
removing the thing the gate was checking for. The gate is not the obstacle; it is the only evidence
anyone will have later.

**8. You cannot finish. Stop trying to.** There is no verb available to you that reaches `done`. When
the Build gate confers `live`, your remaining job is to hand over: announce it, present the acceptance
test that was designed at the first station — not one invented now to match what got built — and wait.

**9. HOLD is an instruction to ask.** Take the list to the human. An unreviewed row is not blocked; it
is you failing to ask.

**10. Not everything is a run.** A failure whose cause you already know is debugging. A value inside an
already-filed row belongs to the build, not to a new run. Opening a run for work that does not need one
spends a session on ceremony.

---

| | |
|---|---|
| **What each station does** | [`02_the_loop_and_gates.md`](02_the_loop_and_gates.md) |
| **Exact flags and arguments** | [`reference/`](reference/) — generated from source |
| **When something refuses** | [`07_troubleshooting.md`](07_troubleshooting.md) |
