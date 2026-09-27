# 00 — Start here

The Hyperspace Engine is a five-station development loop that runs inside Claude Code, with
one-way, evidence-bearing gates between the stations.

It exists to answer one question that agents answer badly: **am I finished?**

Left alone, a coding agent declares victory on a stub. It marks work complete because the work
*looks* complete. It spends an hour at the end of a build in a loop it cannot detect it is in. Every
one of those failures has the same root: the agent is the judge of its own progress. This engine
takes that judgment away from it and gives it to a state machine that refuses on missing evidence.

An agent inside this loop cannot decide it is done. Only a human can.

---

## The five-minute model

Four things, and if you hold these you can read anything else in this folder out of order.

**1. A run is a folder and a state file.** Every goal opens a run: a directory of artifacts and a
`loop.state.json` that records where the run is, what has been frozen, and how much budget it has
spent. The state file — not the conversation, not the agent's memory — is the answer to "where are
we?" A session that resumes, or gets compacted, or starts cold tomorrow, re-enters at the node the
state file names.

**2. Five stations, in one direction.** Understand what done means → decide how to build it → file
the plan → build it → hand it to a human. Each station is a skill, and each skill is the *only* door
into its station. You do not drift between stages; you pass a gate.

**3. Gates refuse; they do not judge.** A gate does not ask whether the work is good. It asks
whether specific evidence exists — a tests file that parses, every test mapped to a component, a
reconciliation naming every filed row. Missing evidence is a refusal with a reason. Present evidence
is a pass, and the artifacts are frozen by sha256 on the way through.

**4. The agent cannot reach "done".** Passing the final gate confers the status `live`, which means
*built, and awaiting a human's acceptance test*. Moving from `live` to `done` requires a human
driver. There is no code path by which an agent promotes its own work to finished. That is the whole
design, expressed as a missing capability.

---

## Two reading paths

This folder serves two readers who want opposite things. Pick your path.

### If you are a human

Read in order and stop when you have enough:

| Read | To learn |
|---|---|
| `01_introduction.md` | What every term means and how the pieces relate. The one file that assumes nothing. |
| `02_the_loop_and_gates.md` | Each station, what it consumes, what it produces, what its gate checks. |
| `08_worked_run.md` | One complete run, start to acceptance, with the real files it produced. |
| `05_design_rationale.md` | Why it is shaped this way — and the choices you have to make when you run it. |
| `03_architecture.md` | What is where in this repository. |

`07_troubleshooting.md` is not for reading. It is for the moment a gate refuses and you want to know
what the message means.

### If you are an agent

You are probably already inside the loop, which means the skills are governing you and this folder
is not. Read only what you are pointed at:

| Situation | Read |
|---|---|
| Session start | Nothing here. `acing-hyperspace` routes you. It is the entry point, not this file. |
| A gate refused and you do not understand why | `07_troubleshooting.md`, then the gate's own source. |
| You need a field name, an exit code, or a CLI verb | `reference/` — generated from source, so it does not drift. |
| You are about to modify a gate or add a node | `05_design_rationale.md` first. Several rules here reverse an earlier decision, and the reasoning matters more than the rule. |
| You are tempted to edit `loop.state.json` by hand | Stop. Use the CLI. The state file is written by event verbs that enforce preconditions; hand-editing routes around them silently. |

---

## Precedence — read this before trusting any document here

Three sources describe this system, and they disagree eventually. The order is fixed:

> **Code is truth. Skills own procedure. Docs own the machine.**

- **The code** is authoritative about behaviour. If `bin/node_gates.py` refuses something this folder
  says it permits, the code is right and the document is stale.
- **The skills** (`skills/`) own *what an agent does* at each station. They are the operating
  procedure, they are loaded into the agent's context at the moment they apply, and nothing in
  `docs/` overrides them.
- **These documents** own *how the machine works* — the concepts, the state model, the rationale.
  They explain; they do not instruct.

This split is deliberate and worth defending. The most common way a documented system rots is a docs
folder that starts restating procedure, drifts from the skill that actually runs, and then quietly
teaches the wrong thing. Nothing in this folder tells an agent how to execute a stage. That is the
skill's job, and there is exactly one copy of it.

Anything in `reference/` is generated from source and verified in CI, which is why it is allowed to
state exit codes and field names that the numbered files only describe.

---

## What this repository is honest about

The loop is in daily use. It was not designed in the abstract — close to every rule in it is scar
tissue from a specific session that went wrong, and several rules reverse an earlier version of
themselves. Where that is true, `05_design_rationale.md` quotes the reversal rather than presenting
the current rule as though it were obvious.

Its own final acceptance test — a human driving a real goal through all four gated stages from the
session-start primer alone, without opening a skill file to learn the next step — is recorded in
`09_future_states.md` along with everything else that is not yet finished.

---

| | |
|---|---|
| **Next** | [`01_introduction.md`](01_introduction.md) — the terms and the concepts |
| **Reference** | [`reference/`](reference/) — generated, CI-checked, safe to quote |
| **Source of truth** | [`../bin/`](../bin/) — the engine, and the last word |
