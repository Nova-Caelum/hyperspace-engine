# 09 — Future states

Where the engine goes next, and the questions that are still open.

Every design worth trusting has edges its authors can name. This file names them — not as a confession
but as the working agenda, because a reader who can see the open questions can tell the difference
between a decision and an accident, and can contribute to the ones that are still live.

Nothing here is a commitment or a dated roadmap. Where something is a genuine open question with two
defensible answers, it says so.

---

## 1. The next milestone: the loop drives itself

The engine holds work to a standard, and the most interesting test of the design is whether it meets
that standard for its own operation.

**The test:** a human drives a real goal through all four gated stages starting from the session-start
primer alone — no opening a skill file to learn what comes next, no intervention to explain the loop
to the agent mid-run.

**Why this is the right test.** Everything else measurable here verifies the machine: tests pass,
gates refuse correctly, state transitions hold. This verifies the *routing* — whether an agent dropped
into a session finds its way to the right station without a human narrating the process. That is the
claim the whole design rests on, and it is the one thing a unit test cannot establish.

**Status:** scheduled, not yet run. The result will be recorded here whichever way it goes. A project
that only publishes the gates it has already passed is not telling you much.

---

## 2. `verifying` — a reserved station

`verifying` exists in the status vocabulary with no gate registered against it. It is currently
unused, and it was kept rather than removed.

There is a plausible station between "built" and "handed to a human" — an automated verification pass
distinct from both the Build gate and the human's acceptance test. Whether that station should exist
is genuinely open:

- **Register a check**, and the vocabulary becomes complete.
- **Remove the value**, and the vocabulary becomes tight.

The value was kept on the reasoning that a closed vocabulary which silently drops entries is harder to
trust than one carrying a documented spare. That justifies today's state; it does not settle the
question, and the question is worth settling deliberately rather than by default.

---

## 3. Whether the node track ever moves again

`current_node` stops at `executing` by design — that is what allows a build to end without the agent
judging itself finished ([`01_introduction.md`](01_introduction.md) §3).

The open question is whether that is permanent. If a station ever sits past the build — a verification
pass, a deployment stage, a post-acceptance step — the node track would need to advance again, and the
two-axis model would deserve a fresh look rather than a quiet extension. Today it reads as an
invariant, and it has not yet been tested against a fifth gated station, because there is not one.

Worth flagging for anyone extending the engine: this is the assumption most likely to bind.

---

## 4. Budget measurement is partial, and labelled as such

Four budget counters exist. Two are detected automatically at session start (`fresh_sessions`,
`compactions`). Two are not (`daniel_hours`, `worklog_entries`) — they carry a cap and no incrementer.

**Each counter states which it is.** The `is_detected` flag exists precisely so a reader can tell a
measured number from an intended one, and that is the right behaviour for a system that refuses to let
an agent assert things it has not checked — the same standard, applied to itself.

The next step is to either wire real detection for the undetected pair or retire their caps. Carrying a
labelled gap is honest; closing it is better.

---

## 5. Personalisation: a deliberate choice with an open horizon

The skills address a specific human by name. A budget counter is called `daniel_hours`.

This is intentional. Close to every rule in the loop is scar tissue from a specific session that went
wrong for a specific person. Generalising the language would make the rules read as though they had
been designed in the abstract, which would misrepresent where they came from and remove the evidence
that each one has a source. The specificity is part of the credential.

As the engine is adopted more widely, three directions are available:

- **Keep it verbatim** — the specificity stays the credential.
- **Template the identity** — keep the incidents that motivated each rule, generalise the name.
- **Separate rule from provenance** — the rule generalises; the incident stays cited beside it.

The third is the most work and probably the most correct. The decision is open, and adopter experience
is the input that should drive it.

---

## 6. HOLD at one gate, and whether it belongs at more

Exit 3 (HOLD) is Build-only. The earlier three checks state explicitly that they have no hold path.

That is coherent: manual criteria attach to filed rows, and rows exist only after the plan is filed.
But HOLD has turned out to be one of the more useful mechanisms in the design — a structured way to
say *a human is needed here, and this is exactly what to ask them* — which is suggestive rather than
conclusive about whether the earlier stations want the same affordance.

Suggestive is not a mandate. Noted, not built.

---

## 7. Resuming a run that has ended

Endings are one-way by construction, and there is no `resume` verb. Reviving an ended run means
editing the state file deliberately, by hand.

The asymmetry is intended: an ending should be hard to undo by accident. What it means in practice is
that a run descoped for resource reasons and later picked back up has no first-class path. The current
answer — open a new run whose input is the old run's frozen artifacts — preserves both records
completely and loses the continuity between them.

Whether a real resume belongs in the design, or whether the two-records outcome is actually the more
honest one, is open.

---

## 8. Drift protection, and where it stops

The precision documents in [`reference/`](reference/) are generated from source, with a test that
regenerates them and asserts the committed copy matches. Documentation drift becomes a failing CI
check rather than a reader's wasted afternoon. That is the strongest guarantee in this folder.

The numbered files carry no such guarantee. They describe concepts and rationale — content that ages
slowly, but not never. A concept document that has quietly stopped being true misleads exactly as much
as a wrong exit code and is considerably harder to detect.

Extending mechanical verification from the reference set to the narrative set is an open design
problem, and an interesting one. No approach is obviously correct yet.

---

## 9. In flight

Work under way at the time of writing, separated from the speculative:

- **Standalone operation.** The engine's external dependencies are being removed so it runs on its
  own. [`03_architecture.md`](03_architecture.md) and [`06_adaptation_notes.md`](06_adaptation_notes.md)
  are written against the result and are authoritative on what changed — this is a pointer, not a
  description.
- **Generated reference set.** [`reference/`](reference/) and its drift test, per §8.
- **Root `CLAUDE.md`.** So an adopter's own Claude Code session recognises a hyperspace-engine checkout
  and behaves correctly inside it.

---

| | |
|---|---|
| **Back to** | [`00_start_here.md`](00_start_here.md) |
| **What is here now** | [`03_architecture.md`](03_architecture.md) |
| **What adaptation changed** | [`06_adaptation_notes.md`](06_adaptation_notes.md) |
