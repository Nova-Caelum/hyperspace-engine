# 09 — Future states

What is unfinished, what is undecided, and what would have to change for each to resolve.

This file is not a roadmap and carries no commitments. It exists because a system that only documents
its finished parts is harder to trust than one that names its open edges. Where something is a
genuine open question rather than a queued task, it says so — an open question with two defensible
answers is more useful to a reader than a confident promise.

---

## 1. The loop's own acceptance test has not been run

The engine holds work to a standard it has not yet met itself.

**The test:** a human drives a real goal through all four gated stages, starting from the
session-start primer alone, without opening a skill file to learn what the next step is. No
intervention to explain the loop to the agent mid-run.

**Why it is the right test:** everything else measurable about this system — tests passing, gates
refusing correctly, state transitions holding — verifies the machine. This verifies the *design*. If
a human has to explain the loop to the agent that is supposed to be running inside it, the routing
has failed regardless of how well the state machine behaves.

**Status:** not run. When it runs, the result gets recorded whichever way it goes. Publishing the gate
you have not yet passed is the point.

---

## 2. `verifying` has no gate

`verifying` sits in the status vocabulary with no check registered against it. It is unused.

Two defensible resolutions, and the choice has not been made:

- **Register a check.** There is a plausible station between "built" and "handed over" — an automated
  verification pass distinct from both the Build gate and the human's acceptance test.
- **Remove it.** An unused value in a closed vocabulary is a small, permanent invitation to
  misinterpretation.

It was left in rather than quietly deleted, on the reasoning that a vocabulary which silently loses
values is harder to trust than one that admits a spare. That reasoning justifies the current state; it
does not settle the question.

---

## 3. The node track stops at `executing` — permanently?

`current_node` never advances past `executing`. That is deliberate and it is what lets a build end
without the agent judging itself finished (see `01_introduction.md` §3).

The open question is whether that is the final shape or an artifact of there being nothing to model
after the build. If a future station sits past the build — a verification pass, a deployment stage, a
post-acceptance step — the node track would need to move again, and the two-axis design would need
re-examining rather than extending. It currently reads as an invariant. It has not been tested against
a fifth gated station, because there isn't one.

---

## 4. Two budget counters are aspirational

Of the four budget counters, two are detected automatically at session start (`fresh_sessions`,
`compactions`) and two are not (`daniel_hours`, `worklog_entries`). The undetected pair has a cap and
no incrementer.

A cap nothing increments is not a measurement. Each counter carries an explicit `is_detected` flag
precisely so a reader can tell which numbers are real — that is honest, but it is a label on a gap
rather than a fix. Resolving it means either wiring real detection or dropping the caps and admitting
the dimension is unmeasured.

`daniel_hours` also carries the personalisation question below.

---

## 5. Personalisation is deliberate, and its future is undecided

The skills address a specific human by name. A budget counter is called `daniel_hours`. This is not an
oversight: nearly every rule in the loop is scar tissue from a specific session that went wrong for a
specific person, and sanding the personalisation off would make the rules read as though they had been
designed in the abstract — which would misrepresent where they came from and quietly remove the
evidence that each one has a source.

The open question is what happens as the engine is adopted by people who are not that person. Three
directions exist, and no decision has been recorded:

- keep it verbatim, and let the specificity be the credential
- template the identity, keeping the incidents that motivated each rule
- separate the rule from its provenance, so the rule generalises and the scar tissue stays cited

The third is the most work and probably the most correct. None is chosen.

---

## 6. HOLD exists at one gate only

Exit 3 (HOLD) is Build-only. The `understanding`, `deciding` and `specifying` checks state explicitly
that they have no hold path — they pass or they refuse.

That is coherent today, because manual criteria attach to filed rows and rows exist only after the
plan is filed. Whether the earlier stations would benefit from a hold path — a way to say *this needs
a human before it can proceed, and here is exactly what to ask* — is unexamined. The Build gate's HOLD
turned out to be one of the more useful things in the design, which is weak evidence that the earlier
gates might want it too, and weak evidence is not a reason to build it.

---

## 7. A run cannot be resumed once it has ended

Endings are one-way by construction. There is no `resume` verb: reviving an ended run means editing
the state file by hand, deliberately.

This is the intended asymmetry — an ending should be hard to undo by accident. But it means a run
descoped for resource reasons and later picked back up has no first-class path. The current answer is
to open a new run whose input is the old run's frozen artifacts, which preserves both records and
loses the continuity between them. Whether that is right, or whether a real resume belongs in the
design, is open.

---

## 8. Documentation that cannot drift

The precision documents in `reference/` — state fields, CLI verbs, gate contracts, status vocabulary
— are generated from source, with a test that regenerates and asserts the committed copy matches.
Drift becomes a failing CI check rather than a reader's wasted afternoon.

The numbered files in this folder are hand-written and carry no such guarantee. They describe
concepts and rationale, which is the class of content that ages slowly — but "slowly" is not "never",
and there is no mechanism that catches it when they do. A concept document that has quietly stopped
being true is exactly as misleading as a wrong exit code and considerably harder to detect.

No mechanism for this exists and none is obviously correct.

---

## 9. In flight

Work under way at the time of writing, named here so a reader can tell what is imminent from what is
speculative:

- **Dependency removal.** The engine's two external dependencies are being removed so it runs on its
  own. `03_architecture.md` and `06_adaptation_notes.md` are written against the result and are the
  authority on what actually changed — this line is a pointer, not a description.
- **Generated reference set.** `reference/` and its drift test, per §8.
- **Root `CLAUDE.md`.** So an adopter's own Claude Code session knows it is inside a hyperspace-engine
  checkout and how to behave there.

---

| | |
|---|---|
| **Back to** | [`00_start_here.md`](00_start_here.md) |
| **What is actually here now** | [`03_architecture.md`](03_architecture.md) |
| **What was changed in adaptation** | [`06_adaptation_notes.md`](06_adaptation_notes.md) |
