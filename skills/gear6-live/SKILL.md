---
name: gear6-live
description: Use when a run's software is finished and the engine has conferred status live — every row built, wired, promoted, deployed and verified, and only Daniel's real-world test remains. Fires on a resumed session whose loop.state.json reads status live, and when Daniel says "we're live", "run the acceptance test", "sign this off", or "is this done yet". The stage after Build; nothing is built here.
derives_from: nova-caelum
license: MIT
author: Nova Caelum
version: 1.0
---

# gear6-live — the Live stage (N5)

## Overview

The stage between finished software and a finished run. Build ends when the machinery says so — `gate-pass --node executing` exits 0 and sets `status: live` — not when you decide you are finished. What remains is not work. It is Daniel driving, in a real production workflow, the acceptance test the run wrote for itself at the start, while you watch.

This stage exists because the run before it had no ending. A real run — `governance-evolution-sprint/numeric-ref-enforcement` — was built, promoted, merged, deployed and runtime-verified on 2026-09-15, and its build node kept absorbing work for two more days: three defects found and routed, two follow-up rows filed, every one of them real, not one of them the run's goal. Daniel named the class: *"Getting stuck in these endless loops at the end of build mode are the cancer we have been facing."*

**Core principle:** `live` is an announcement, not a victory claim. Announcing costs nothing and asserts nothing. Only Daniel's `confirm` makes it `done`.

## The Rule

Stop building. Announce. Hand Daniel the acceptance test the run designed at the start. Then wait — run nothing until he tells you to, and when he does, run ONLY the test. Bugs are the test working, not the test failing. Classify each one: a blocking bug stops the test, gets a real fix done properly, and the test restarts from square one; everything else gets one line and the test keeps moving, untouched. Triage happens ONCE, at the end, on the whole list. The exit is `confirm`, which the engine refuses from any authority but a human.

## When to Use

Fires when:
- `loop.state.json` reads `status: live` — read it, never infer it
- `gate-pass --node executing` has just exited 0
- Daniel says "we're live", "run the acceptance test", "sign this off", "is this done yet", "did the test pass"

Does NOT fire for:
- Any row still open, or a gate that exited 1, 2 or 3 → `gear5-build`; the status is the predicate and the machinery sets it
- A defect serious enough to invalidate the build → say so, name it, and let Daniel decide whether the run returns to Build. That is his call, not yours.
- A new goal that surfaced during the live test → `gear2-understand`, as its own run

## The Process

1. **Read the state.** `python3 $AGENTOS_ROOT/system/bin/loop_state.py read <state>`. Confirm `status: live` on the file. Do not set it, and do not proceed on a status you reasoned your way to.
2. **Stop.** No edits, no dispatches, no promotes, no deploys. Close any implementer still running. Append one ledger line: `Live: build closed at <gate timestamp> — <N> rows done by verifier verdict.`
3. **Recover the acceptance test.** It is the run's own `tests.json`, frozen at the framing gate, plus any acceptance criterion still carrying a `manual` verification. Quote it — do not restate it, do not improve it, and do not substitute what you now think the test should have been. If the frozen test no longer matches what was built, that mismatch IS the finding: state it plainly and let Daniel judge it.
4. **Announce, in one screen.** The announcement is a fixed shape: what is live · where it is live (the merge commit and the deploy, each verified by readback, not by a status message) · the acceptance test, verbatim, as steps Daniel performs · what you will be watching · what a clean pass means. Nothing in the announcement asserts that the test passed.
5. **Wait, then run only the test.** Daniel decides when the test runs. Until he says so you run nothing — no setup, no warm-up, no "quick check that it still works." When he says run it, run the test and nothing beside it.
6. **Classify every finding; fix almost none.** A bug surfacing here is the test doing its job. For each one, ask ONE question — *can the test continue without this?*
   - **Blocking** (the test cannot proceed): stop the test and surface it to Daniel immediately with what you observed. On his go, fix it *properly* — the real fix that makes the product better, never a bandaid to get moving again. If it needs major revamping, it needs major revamping: lock in, change what actually has to change, surgically, and nothing beside it. Then **rerun the test from square one.** A blocking fix invalidates everything the test proved before it, so a partial re-run proves nothing.
   - **Non-blocking** (the test can keep moving): ONE ledger line — what, where, what you saw. Then carry on with the test. Do not diagnose it, do not size it, do not fix it, do not file it yet.

   Never interrupt the run for a non-blocking bug. Fixing them as they appear is what breaks the next thing and starts the loop this stage exists to end.
7. **Triage once, at the end.** With the test finished, put the whole list in front of Daniel together and decide each one: fix now · defer to v2 · not a bug. Judged as a set, most of them are small — that is the judgement the mid-test fix denies you. File the keepers as `ready` rows for a later run. Whatever comes back as "fix now" is a new run, entered at its own node — not more work inside this one.
8. **Exit.** Daniel's word that the test cleared → `python3 $AGENTOS_ROOT/system/bin/loop_state.py confirm <state> --by daniel`. `status: done`, `final_route: done`. Then the finish: the `Rulings I made` list, and the escape-rate line the confirm wrote.

## The grade

A clean pass — the frozen test achieved in a real workflow with no troubleshooting, no patch, no "one small fix first" — is the highest result this engine produces. A test that ran end to end with a list of small findings triaged at the close is the ordinary good outcome, and it is not a failure. Daniel: *"if there are no issues... that is the grandest most incredible win."* Report it as the win. A run that needed three repairs before its test cleared also reaches `done`, and it is not the same grade. Say which one happened.

## Exit gate

This stage exits ONLY through `confirm`, and `confirm` refuses:
- any `status` other than `live` — a run that never passed the Build gate cannot be confirmed
- any driver whose `authority` is not `human` — you cannot confirm on Daniel's behalf, by design

There is no `gate-pass --node live`. `live` is a stage you sit in, not a node you exit; no exit check is registered for it and `gate-pass` refuses it outright.

`$AGENTOS_ROOT` is the canonical `_agentOS` root (this Mac: `$AGENTOS_ROOT`).

## The four stops

Return to Daniel only for: an irreversible or destructive operation · a security-sensitive action · a side effect outside the workspace that norms say you ask about first (a merge, a publish, an external send) · a plan so broken that every path forward is a guess. Everything else is a ruling — decide it, ledger it with its cost, keep going.

The live test itself is not a stop. It is the stage.

## Red Flags

If you catch yourself thinking:
- "This one is real and it will only take a minute" → it is real, and it is a filed row. The numeric-ref run's three findings were all real; that is exactly how two days disappeared.
- "I reproduced his test and it passed" → you ran a proxy. INC022 named self-reported success with no state change the system's signature failure, five instances in one night. His test is his.
- "I'll run it now so the result is ready when he asks" → he did not say run it. Running early is running without a driver, and the result is not his test.
- "It failed, but one fix and it's clean" → ask the one question instead: can the test continue? If yes, it is a line in the list and you keep going.
- "A quick patch gets the test moving again" → a bandaid on a blocker buys a test result about the bandaid. Fix it properly or do not fix it.
- "The fix was late in the run, so I only need to re-test from there" → the fix changed the thing the earlier steps exercised. Square one.
- "I'll just fix this one while I'm here" → that is the loop, in its own words. The fix you make mid-test is the bug you find next.
- "I should work out how bad this is before I log it" → sizing it IS the interruption. One line, keep testing, judge the set at the end.
- "I should fix it before he sees it" → he is testing the thing that was built, not the thing you wish had been built. Hiding the defect corrupts the only real signal this stage produces.
- "Nothing is happening, so I should find something useful to do" → nothing happening IS the highest grade. Idle is the shape of success here.
- "The build is obviously finished, I'll just set live and move on" → `set-node` cannot confer `live`, on purpose. If the gate did not confer it, the build is not finished.
- "He said it looks good, that's the sign-off" → `confirm` needs his word on the test, not on the announcement. Ask him plainly.

## Common rationalizations

| Rationalization | Reality |
|---|---|
| "Routing this defect is the disciplined thing to do" | Filing it is. Fixing it is Build, and Build is closed. The discipline and the excuse are the same sentence here — that is why this row exists. |
| "Stopping means declaring done, and I cannot verify done" | Correct, and you are not declaring it. `live` asserts only that building stopped. INC022's other half was declaring `done` before verifying; the two-state split exists so you do neither. |
| "One small patch keeps the test clean" | Then the test result is about the patch, not the build. A clean pass is only meaningful on the artifact that was gated. |
| "I can grade the run myself; the evidence is right here" | The confirm refuses non-human authority in code. That refusal is the design, not an obstacle to route around. |
| "The frozen test is worse than what I would write now" | Say so, out loud, as the finding. Rewriting it mid-stage destroys the one comparison the run was built to make. |
| "The deploy reported success, so it is live" | A status message is not a readback. Verify the artifact in the runtime before you announce it, or the announcement inherits INC022 Class 1 (green status, nothing happened). |

## Self-Check

Before the announcement: does `loop.state.json` read `status: live` on disk? Is every edit of mine promoted and deployed, and verified by readback? Is the test I am handing him the frozen one, quoted?

Before `confirm`: did Daniel say the test cleared — not that the work looks good? Is every issue found during the stage either a filed row or an explicit "none"? Am I about to state a grade the evidence supports?

## Out of scope

- Building, patching, promoting, deploying → all of it belongs to `gear5-build`, and Build is closed
- Auditing what was built → CTO, via Daniel
- A new goal discovered during the test → its own run, from `gear2-understand`
- Deciding the run failed → you report; Daniel decides whether it returns to Build

## Source

Daniel's decision of 2026-09-16, recorded verbatim on row `nova-caelum-framework:loop-ending-executing-live-done`. Pressure-scenario baseline (three observed failures, three sources): `AgentSecretBase/workspace/hyperspace-engine_new_sprintframework/build/live-stage/gear6-live-baseline.md`. Failure sources: INC022 (infrastructure gravity — six hours, zero rows advanced), the `numeric-ref-enforcement` run's two-day tail after deploy, and Daniel's naming of end-of-build loops as the cancer.
