# 05 — Design rationale

Why the engine is shaped this way, and which choices you have to make when you run it.

Two kinds of content here, kept apart on purpose:

- **§1–§12 are design decisions** — already made, with the reasoning preserved. Several reverse an
  earlier version of themselves, and where that is true the reversal is quoted rather than hidden.
  Read these before modifying a gate; the rule matters less than why it is that rule.
- **§13–§15 are your decisions** — the choices an adopter faces, with what each option costs and buys.

---

## Part one — decisions already made

### 1. The founding constraint: the agent is not the judge

Every other choice follows from one observation. An agent asked both to do work and to assess the work
will drift toward the assessment that lets it stop. Not through dishonesty — through the ordinary
gradient of a system optimising for task completion, where "declare complete" is always the cheapest
remaining move.

The response is structural rather than instructional. Telling an agent to be more rigorous produces an
agent that is more rigorous for a while. Removing its ability to render the verdict produces an agent
that cannot make the error at all.

Read the rest of this file as consequences of that one sentence.

### 2. Why gates check evidence, not quality

A gate has no opinion about whether the work is good. It asks whether specific artifacts exist and
parse.

This is a deliberate narrowing, and it is what makes the gate trustworthy. A gate that judged quality
would need a model to do the judging, which reintroduces exactly the thing being removed: an
agent-shaped assessment of whether agent work is good enough. A gate that checks for a parsing tests
file, a complete mapping, a backfilled id, a reconciled row — that gate can be wrong about
importance, but it cannot be talked round.

Quality judgment lives where it belongs: with the human, at the acceptance test, on criteria written
before anyone knew how hard the work would turn out to be.

### 3. Why the loop is one-way

Each station consumes the frozen output of the one before. The Decide gate maps tests to components;
without frozen tests there is nothing to map. The Draft gate proves rows were filed; without a
decision there is nothing to file. The Build gate reconciles filed rows; without rows there is nothing
to reconcile.

So the ordering is not a workflow preference. **Skipping a station does not save time; it deletes the
evidence the next gate reads.** The loop is one-way because the evidence chain is.

### 4. Why `current_node` and `status` are separate axes

The obvious model — one pointer advancing through stages to `done` — cannot express the state that
matters most: *built, and awaiting a human's verdict.*

So there are two tracks. Passing the Build gate sets `status: live` and leaves `current_node:
executing` alone. `confirm` moves `status` to `done` and also leaves `current_node` alone. The node
track goes flat at `executing` while the status track keeps moving.

This is the mechanism by which a build *ends.* The agent arrives somewhere it is no longer permitted
to build, without ever having judged itself finished. The permission was withdrawn by a gate rather
than surrendered by the agent — and those are very different things when the agent is the one
reporting.

### 5. Why the Build gate moved earlier

An earlier design held the Build gate until every criterion was discharged, including the manual ones
only a human can supply.

The result was a finished build that still looked, from inside the session, exactly like building. The
agent could not tell it was done, so it kept going — which is the original failure mode wearing a
gate-shaped costume. In the operator's words at the time, *"the cancer we have been facing."*

The gate now confers `live` as soon as the work is built, wired and deployed, and the human's test
becomes its own stage. The lesson generalises: **a gate placed where the agent cannot satisfy it
recreates the loop it was meant to end.**

### 6. Why manual criteria hold the gate — a reversal worth reading

The first version let manual criteria defer to the live stage: build finishes, unresolved manual
criteria carry forward, gate passes. That was reversed deliberately, and the reasoning inverts the
obvious framing:

> *"If a criterion requires manual verification, and that row is left unclosed, that is a failure on
> the agent to not adequately direct me that they had completed work that was ready to be reviewed."*

The intuition being corrected is that an unreviewed row is *blocked* — waiting on someone else,
nothing to be done. The correction: an unreviewed row is the agent **failing to ask.** Requesting
review is part of the work, not a thing that happens to the work.

Hence HOLD names every affected row and quotes its criterion. That list is an agenda, not an error.

### 7. Why HOLD exists at one gate only

Manual criteria attach to filed rows, and rows exist only after the plan is filed. The three earlier
checks state explicitly that they have no hold path — they pass or they refuse.

The deeper reason to keep it narrow: a hold path is an escape hatch, and escape hatches migrate. One
gate that can say "a human is needed" is a mechanism. Four gates that can say it is a habit, and a
habit of pausing for a human is indistinguishable from not having gates.

### 8. Why refusals collect every cause

The gates resolve as far as they can and report every problem at that level at once — all missing
mapping keys together, all unreadable referenced files together, every unmapped test id and every
component-level cause together.

The alternative is failing at the first problem, which turns one fix into six rounds of discovering
one more thing. Each round costs a session, and sessions are the budgeted resource. A refusal is
meant to be a complete work order.

### 9. Why the contract is imported lazily and never vendored

The Understand gate validates its tests file against a schema contract. Two choices there, both
deliberate.

**Never vendored.** A copy of the contract inside this repository is a copy that drifts, and a
validator checking against a stale schema gives a confident pass on a document the real system will
reject. The gate imports the live contract or refuses with the import error — a loud failure rather
than a quiet wrong answer.

**Imported lazily, inside the function.** The contract brings a validation library (Pydantic) with it.
Importing at module level would load it for every consumer of the module, including the Build check
and its tests, which need nothing from it. Lazy import keeps that dependency on exactly one code path.

The wider principle: the strict, well-typed validator is worth its weight where a document must be
rejected precisely, and worth avoiding everywhere else. The Decide gate reads raw JSON and markdown;
the Draft gate reads text through a sibling parser. **One validation dependency, one code path, and
three gates that need no third-party code to run.** That is also why the test suite runs on the
standard library with no configuration.

### 10. Why the Draft gate checks ids rather than plan quality

The Draft gate reads `Plan.md` as text and checks that every task block carries a non-blank,
UUID-shaped `task_id`. It applies no lint rule at all.

The filing step writes those ids back into the plan. So a blank id is not a formatting defect — **it
is a row that was never filed.** The gate is not assessing the plan; it is testing whether the plan's
claim to have filed work is true.

A lint rule was deliberately excluded. Plan quality is the author's self-check. Conflating the two
would give the gate an opinion, and §2 explains why it must not have one.

### 11. Why dispositions are not interchangeable

At the Build gate every filed row needs a disposition: `done`, `deferred`, `archived`, or `live-test`.
Three of those skip the verifier check; `done` does not.

The asymmetry is the point. `deferred` and `archived` mean *not built* — there is nothing to verify, and
descoping openly is a legitimate outcome. `live-test` means *cannot begin until the run is live.*
`done` means *built*, and built work must prove it landed.

Critically, **the reconciliation artifact cannot rescue a `done` row.** If the verifier says otherwise,
the row refuses or holds regardless of what the artifact claims. Otherwise the artifact becomes a
self-certification form, and the gate becomes a formality.

A row absent from the artifact refuses outright. That absence is the exact hole this gate exists to
close — a row that looked done and was never closed. Silence about a row is the failure, so silence is
not allowed.

### 12. Why endings are derived and cause-blind

A run's ending is computed by a predicate reading state. It takes no outcome argument from any caller,
so no agent can request an ending. And it is cause-blind: it reads *whether* a kill fired, never *why*.
The why is recorded for a human, separately, and never gates the route.

Two statuses — `abandoned_budget` and `blocked_external` — are kill triggers rather than endings, and
route to `killed`. The reasoning: a run that quietly dies of budget exhaustion is the same class of
failure as a row that quietly never gets filed. Both must resolve to a named outcome rather than
sitting unresolved forever. An unresolved thing is invisible, and invisible things do not get fixed.

---

## Part two — decisions you make

### 13. The model behind the evidence judge

Closing a row on evidence involves a judgment step: given the criteria and the delta the work
produced, was the criterion satisfied? That step needs a model, and you supply it.

What the choice affects, in rough order of importance:

- **Refusal quality.** A weaker model refuses less precisely — it is likelier to return
  `unverifiable` where a stronger one would have returned a specific, actionable refusal. Since
  `unverifiable` routes to a human, a weaker model converts machine work into human work. That is the
  real cost, and it is paid in the scarcest resource in the system.
- **False passes.** The expensive failure. A model that accepts a plausible-looking claim reintroduces
  the founding problem at the last possible moment, after every gate has been satisfied.
- **Per-close cost.** Every closure is a call. Frequent closes make a cheap model attractive; see the
  first two bullets before acting on that.

**Recommendation:** use your strongest available model here, even where you would economise elsewhere.
This is the one place in the loop where a wrong answer is both consequential and hard to notice — a
false pass looks exactly like a pass.

Specific providers, keys and configuration are in the setup instructions, which are authoritative;
this section is about the trade-off, not the wiring.

### 14. What "done" means in your criteria

The single highest-leverage decision you make, and it is not a configuration setting.

Every gate measures against the criteria written at the first station. Write them loosely and the loop
runs perfectly while catching nothing — gates pass, the state machine behaves, and the acceptance test
finds everything. `escape_rate` is the number that exposes this after the fact.

Two rules the gate enforces for you, both worth understanding rather than working around:

- **At least one non-`manual` criterion.** A criterion only a human can judge cannot discharge itself.
  Keep the judgment criteria; add an executable one beside them.
- **At least one `WHOLE-PATH:` criterion.** A set of individually-passing units routinely describes a
  system that does not work end to end. Something must assert the seam.

And the rule the verifier enforces: **evidence is a delta.** A criterion already satisfied before the
work started does not discharge it. Write criteria about what the work will *change*, not about what is
already true — otherwise you will write criteria that pass on day one and mean nothing.

### 15. How much ceremony a task deserves

The loop scales down. A one-line fix does not need a PRD, and running the full five stations for it
wastes a session.

The rule is: **ceremony scales with the task; the gate never does.** Compress the artifacts; do not
skip the evidence. A small run can have a two-criterion tests file and a one-component mapping — what
it cannot have is a Build gate that never reconciled its rows, because the evidence chain is what the
next station reads.

A failure whose cause you already know is debugging, not a loop run. Not everything is a run, and
treating everything as one is its own failure mode.

---

| | |
|---|---|
| **The mechanisms these reasons explain** | [`02_the_loop_and_gates.md`](02_the_loop_and_gates.md) |
| **Open questions still being decided** | [`09_future_states.md`](09_future_states.md) |
| **When a gate refuses** | [`07_troubleshooting.md`](07_troubleshooting.md) |
