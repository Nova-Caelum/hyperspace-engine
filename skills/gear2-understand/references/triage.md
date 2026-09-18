# Triage — the three paths (gear2-understand)

Ported from obra/superpowers `brainstorming` 6.3.0 (MIT) §"Three Paths", §"Anti-Pattern" and §"Red Flags", archived at `01_research/upstream-source-6.3.0/skills/brainstorming/SKILL.md`. What changed: upstream's human-approval HARD-GATE is replaced by the validator gate (`gate-pass --node understanding`); "bounded" keeps upstream's test (an existing flow on disk) and gains a size (a one-screen `Problem.md`); **the spike writes nothing** — no state file, no gate, no documents — which is the Plan T4.3 note verbatim and the reason this file exists (PRD §3.1(b); baseline row 5). Read by the node at step 1; the call is recorded by `demi-understand-problem-depth` under `## Path`.

## Say it before the first question

Classify, then say the classification out loud — *"this looks bounded, so I'll open a run with a one-screen `Problem.md` and a short `tests.json`"* — so Daniel can override before any work. When in doubt between two, take the heavier. Reaching for the lighter label to skip the gate IS the doubt.

## The three paths

| | Spike | Bounded | Architectural |
|---|---|---|---|
| **What it is** | A feasibility question — "can we…", "is it possible…", "quick and dirty is fine" — whose output is an ANSWER, not a thing you keep | A well-scoped change to something that already exists and can be read on disk: a flag, a small endpoint, one more argument, a one-file fix | A new project, subsystem or skill; a change that restructures how components fit or alters an interface others depend on |
| **The test** | Would the deliverable be thrown away once the question is answered? | Can you name the file or flow that changes, and read it now? Knowing the KIND of thing is not enough — if there is no existing flow to change, it is not bounded | Is there no existing flow to change, or will the change move a boundary other things rest on? |
| **What it costs** | **Nothing.** No `init`, no `loop.state.json`, no `01_understand/`, no `Problem.md`, no `tests.json`, no gate, no ledger line | `init` + `set-node understanding` · `Problem.md` ≈ one screen · `tests.json` — a few criteria, ≥1 executable, one `WHOLE-PATH:` · the gate | `init` + `set-node understanding` · `Problem.md` as long as the constraints need · full `tests.json` · the gate · N2 with real options |
| **How it ends** | A recommendation in chat: the question, what was tried, the answer. Anything built is labelled throwaway | `gate-pass --node understanding` exit 0 → `gear3-decide` (short at N2 for bounded work) | `gate-pass --node understanding` exit 0 → `gear3-decide` with options |
| **What never scales** | — | The gate: ≥1 non-`manual` criterion, ≥1 `WHOLE-PATH:` — the same for a flag as for a subsystem | Same |

Ceremony scales with the path. The validator run does not.

## Why the cheap path is genuinely cheap

PRD §3.1(b): *"if the lightest path still costs a state file, people stop invoking the node and we are back to ad-hoc specs landing in `_artifacts/`."* Observed 2026-09-07: 102 files in `AgentSecretBase/workspace/_artifacts/`, six of them PRDs, plans and specs written outside any loop, none with a tests file. A spike that cost even a state file would be skipped, and the goal it was probing would reach N2 with no `Problem.md`. So the spike costs nothing and registers nowhere — a design decision, not an omission: the state file `init` writes at bounded / architectural entry is the goal's registration for the C13 denominator, and a spike is not a goal, it is a question about one.

Two consequences:
- A spike's follow-up — *"the probe worked, keep it"* — is a NEW request. Classify it again; it is usually bounded. Throwaway code is not promoted by relabelling.
- A spike never opened a run, so `gate-pass` has nothing to gate; its exit is the recommendation in chat. Do not `init` a run afterwards to "record" it.

## The ratchet is one-way

Hidden complexity discovered mid-run upgrades the path. Stop, say so, step up:
- **spike → bounded / architectural:** the answer turned out to be a thing you keep. Open the run now (`init`, `set-node understanding`); the probe's findings go under `## Problem`; nothing built is carried in as done.
- **bounded → architectural:** the "one file" touches a boundary. Re-mark `## Path` in `Problem.md` with why; widen `## Constraints` and the register; `tests.json` gains the criteria the wider scope needs. If `tests.json` was already frozen, the edit is a double-back the state layer records by hash — say so in the ledger.

Nothing downgrades mid-run. An architectural run that turns out small finishes as a short architectural run; it does not become a spike after the fact.

## Red flags

| Thought | Reality |
|---|---|
| "This is too simple to need tests" | Simple means a short `tests.json`, not no `tests.json`. Two criteria and a `WHOLE-PATH:` line, then the gate. |
| "I'll call it a spike and skip the gate" | Reaching for a label to skip work IS the doubt — take the heavier path. |
| "I understand this kind of system, so it's bounded" | Bounded measures what is on disk, not your familiarity. A new project has no existing flow — it is architectural. |
| "The spike works, so I'll keep the code" | A spike's output is an answer. Keeping the code is a new request — classify it. |
| "It grew, but I'm almost done — no need to re-classify" | Hidden complexity upgrades the path mid-run. Stop and say so. |
| "They approved the spike, so the follow-up change is approved too" | Each request gets its own classification and its own gate. |
| "I'll open a run for the spike just to be safe" | Then it is not a spike, and the C13 denominator gains a goal that was a question. Safe is the heavier PATH, not heavier ceremony on the lighter one. |

## Three one-liners

- *"Can `codex exec` run inside a git worktree without `--skip-git-repo-check`?"* → **spike.** Try it, report, throw the scratch away.
- *"Add a `--tests` argument to `loop_state.py gate-pass`."* → **bounded.** The function and its argparse block exist on disk; one screen of `Problem.md`, three criteria, one of them `WHOLE-PATH: gate-pass --node understanding --tests on a valid file exits 0 and the state file shows both artifacts frozen`.
- *"Build the Understand node."* → **architectural.** No existing flow; a new skill with two demis and a gate other nodes depend on.
