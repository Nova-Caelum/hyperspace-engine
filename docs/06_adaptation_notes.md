# 06 — Adaptation notes

What this plugin was adapted from, what changed on the way, and where the seams are. When something
here looks unusual, this file tells you whether it is a design choice of the loop or a consequence of
running it standalone.

The engine was built and hardened inside Nova Caelum's own operating system, against hosted services:
a task graph behind a private MCP server, a verifier service holding two credentials, and a hosted
console. v0.1 moves every one of those onto your machine. The loop's rules — its gates, exit codes,
freeze semantics and endings — came across unchanged. The line-by-line ledger is
[`../bin/PORT_NOTES.md`](../bin/PORT_NOTES.md); the vendored verifier's provenance is
[`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md). This file is the map over both.

---

## 1. Direction and invariants

The source engine stays canonical. Changes flow one way, source → port, and each port change is
recorded in `PORT_NOTES.md` with its before, after and reason.

Held constant across the port:

| Invariant | Where it lives |
|---|---|
| Five stations, four gated nodes, `live` as a stage | `bin/node_gates.py` `CHECKS` |
| Gate exit codes 0 / 1 / 2 / 3, HOLD at Build only | [`reference/gate-contracts.md`](reference/gate-contracts.md) |
| Freezing by sha256; re-hash mismatches recorded as double-backs | `bin/loop_state.py` |
| `current_node` and `status` as separate axes; `confirm` reserved to a human driver | `bin/loop_state.py` |
| Endings derived from state and cause-blind | `bin/loop_terminal.py` |
| Verifier outcomes: exactly `done`, `refused`, `unverifiable`, `already_done` | `hyperspace/verify/` |
| Evidence is a delta: already true at filing never discharges | `hyperspace/verify/delta.py`, `landing.py` |

Two canonical fixes that landed the day of the port were carried across with their tests: `descope`
and `record-kill` mirror the ending into `status`, and `init` refuses an occupied goal slug unless you
pass `--force`.

---

## 2. Infrastructure: hosted services became local components

| In the source engine | In this plugin |
|---|---|
| A hosted task graph (Postgres) behind a private MCP server | `.hyperspace/graph.db`, one SQLite file, behind the plugin's own stdio MCP server `hyperspace` |
| Proposals queued, adjudicated by a background attempter, then filed | `upsert_work_item` validates the contract and writes the row and its filing directly. No queue, no receipts. |
| A verifier MCP server authenticated with two bearer credentials fetched from a secrets manager | An in-process verifier with no credentials; it writes `completed_by = hyperspace-verifier` itself |
| A hosted console reached over the network with a bearer token | The loopback door on `127.0.0.1`, no authentication, serving a prebuilt console |
| One judge model, configured centrally | Five selectable judges, chosen per project in `.hyperspace/config.toml` |

The result is the property the release was built for: nothing in a project depends on a service off
the machine. The `no_nova_infra` and `no_vault_refs` probes scan the shipped tree for any reference
back to the source system on every CI run.

---

## 3. The acceptance contract

| Change | Why |
|---|---|
| **Vendored.** `hyperspace/contracts/candidate.py` is a copy with a provenance header; the source engine imported the live contract from its own library. | An installed plugin has no source library to import from. One copy in the package serves the Understand gate, the graph tools and the verifier, so they cannot disagree with each other. |
| **Still imported lazily** by the Understand gate, and a missing `pydantic` refuses with one line naming the fix. | The other three gates keep running on the standard library alone. |
| **Two fields renamed:** `user_stated_type` and `user_stated_action`. | The source names carried a person's name. Types and meaning are unchanged. |

---

## 4. The verifier as a graph

The source verifier was a five-step function. Here it is a `pydantic_graph` graph of five nodes —
`Vet → CriteriaQuality → Landing → EvidenceJudge → Commit` — whose bodies are the source steps, moved.
The graph shape makes each junction a node you can inspect, and the run's state is written to the
store's `verifier_runs` table at every junction.

| Adaptation | Detail |
|---|---|
| Backend | Row reads, criteria resolution, the commit and the readback go to `Store` instead of the hosted graph. |
| `filed_at` | The filing's timestamp, not the row's creation time — a criteria update mints a new filing and restarts the delta window. |
| Path root | Touched paths and criterion paths resolve against the project root (the directory holding `.hyperspace/`). |
| Manual attestations | A `manual` criterion discharges only against an attestation whose `attested_by` equals the configured `user` (default `user`). Unattested stays `uncertain`, never a silent pass. |
| Judges | The judge calls sit behind a `Judge` protocol with five runners. A judge error gets one retry, then `uncertain`. |

**The one intended behavioural divergence: `judge = "none"`.** With no judge configured, the two
semantic steps record `skipped` without calling anything, and the row closes `done` exactly when the
Landing step discharged every criterion; if Landing left any criterion uncertain, the outcome is
`unverifiable`. That gives you keyless closure of deterministic criteria — `file_state`,
`command_check` — on a machine with no model access at all. Under every other judge the semantic steps
run exactly as in the source.

---

## 5. Filing and the plan

The source engine filed a plan's rows with a batch uploader that also wrote the row ids back into
`Plan.md`. The plugin files through the MCP server instead: `upsert_module` per module,
`upsert_work_item` once per task block, `link_work_items` per dependency, with each returned row id
written into its block's `task_id`.

The Draft gate's check did not change. It still refuses a blank or non-UUID `task_id`, because a block
without a returned id is a row that was never filed.

---

## 6. Helper skills folded into the stations

The source loop leaned on six helper skills. Shipping them would have tripled the plugin's skill
surface for behaviour each station needs only a few sentences of. Their rules now live inline, in the
demi that uses them:

| Source helper | Now |
|---|---|
| Contract-writing rules | Inline in the test-writing, plan-writing and filing demis |
| Placement (module, work item or sub-step) | Inline in the test-writing and filing demis |
| Closure | Every closure goes through the `hyperspace` server's `complete_workitem` |
| Assumptions register | Inline in the problem-depth and option-generation demis |
| Over-engineering review (five advisory tags) | Defined in the descoping demi; the station refers to it by name |
| Evidence before closure | Each gate block's evidence line; at Build, the row's RED→GREEN run in its report |

Templates that no gate reads became a one-line statement of the required sections in the demi's own
self-review; the template that a demi copies (`candidate-template.json`) ships with the skill.

---

## 7. Budget counters: measured fields only

The source state file declared four budget caps, two of which nothing ever counted. The port
writes only what is counted — `fresh_sessions` and `compactions`, each a `{cap, used}` pair — and drops
the other two from the state file and the schema. A field that asserts a measurement nobody makes is a
false statement in the schema, and removing it is more honest than labelling it.

The counters are incremented by `loop_state.py bump --event startup|compact`, which the source system
calls from a session-start hook. This plugin ships that hook (`hooks/session-start.sh`, wired by
`hooks/hooks.json`): on every `SessionStart` it calls `bump` and `notify` for every non-terminal run
under `hyperspace/runs/`, so `used` moves off zero from a real session the first time `startup` or
`compact` fires. `notify` and the frozen-on-ending rule work unchanged.

---

## 8. Identity, wording and provenance

The loop's rules were written in one operator's system, against real incidents. The port keeps the
rules and their provenance and drops the private coordinates:

| Before | After |
|---|---|
| A person's name where the text meant the human driving the loop | "the user" |
| Quoted rulings and lessons | Kept verbatim, attributed to "the author" or "a prior run" |
| Links to private incident files, ledgers and archives | Neutral provenance with the date kept — for example "an internal incident record (INC014, 2026-06-21)" |
| Fully prefixed tool names for the hosted servers | "the `hyperspace` MCP server's `<tool>` tool" |
| Review header on authored documents | `**User reviewed:** no` |

Every skill's `name:`, the six gear directory names, and every rule, gate, exit code and ceremony are
unchanged.

---

## 9. Paths, labels and defaults

| Item | Source engine | Plugin |
|---|---|---|
| Script calls | An environment variable pointing at the source library | `.hyperspace/env/bin/python "${CLAUDE_PLUGIN_ROOT}/bin/<x>.py"` |
| Interpreter | Whatever `python3` the shell found | The project's `.hyperspace/env` |
| Run folders | Under the operator's private workspace | `<project>/hyperspace/runs/<slug>/` |
| Verifier run files (Build gate default) | A home-directory path | `<run-dir>/misc/verifications/` |
| Closure labels the Build gate accepts | The source committer and console labels | `hyperspace-verifier`, `hyperspace-console` |
| An agent writing `state="done"` through `upsert_work_item` | Refused on create and update (ops server 0.9.15, 0.9.17); the console is exempt | The same: the MCP tool refuses; the loopback door's `/mcp` and `PATCH /api/work-items/<id>` handlers are the console and stamp `hyperspace-console` |
| Owner the console offers first | The operator | `user`, set at build time with `VITE_HUMAN_OWNER` |

---

## 10. The console

The console is Caelos, the same code the source system runs, built at a pinned commit and shipped as
static files. Three build choices adapt it: a relative API base (`VITE_API_BASE_URL=.`) so one bundle
works on any port; a neutral pinned owner (`VITE_HUMAN_OWNER=user`); and neutral demo data. The door
serves only the routes the console reads, plus `POST /mcp` for its writes. Rebuilding is
`ui/build.sh`; the pin and commands are in `ui/SOURCE.md`, and CI checks that a rebuild reproduces the
shipped files.

---

## 11. Deliberately not shipped

| Left out | Reason |
|---|---|
| The background attempter and its adjudication graph | Direct filing needs no queue; a single-user project has no one to adjudicate between. |
| The plan uploader | Filing is per object through the MCP server (§5). |
| The section-shape lint and its templates | No gate read them (§6). |
| The history-rewrite gate | Not part of the loop; the `known_defects` probe confirms it is absent. |
| Agent registry | `list_agents` is a local stub that returns the configured judge. |

---

## 12. Seams to know about

Places where the standalone plugin and the source engine still meet at an angle. Each is a boundary
of v0.1 with a known next step.

| Seam | What it means today | Next step |
|---|---|---|
| Build gate evidence | The local verifier records its runs in the store's `verifier_runs` table, not as files under `misc/verifications/`. Run the Build gate with `--graph-snapshot` (a saved `list_work_items` result): verifier- and console-closed rows then pass by their `completed_by`. A row that is not `done` in the graph refuses by name; the HOLD enumeration of manual criteria reads verifier run files, so it does not fire from the store yet. | Export verifier runs to the run folder, or teach the gate to read `verifier_runs` |
| Windows | Supported since v0.1.3: `.mcp.json` runs `.hyperspace/env/bin/python` directly (on Windows `env/bin` is a junction to `env/Scripts`), and the SessionStart hook runs under Git Bash. Verified in CI with the real `claude` binary; the interactive path is proven on a real Windows 11 PC by the user. | Anything the first real Windows 11 run surfaces |
| Headless sessions | `claude -p` denies any tool that needs approval; the whole-path probe pre-approves exactly the tools its goal needs. Interactive sessions ask you as usual. | — |
| Judge coverage in CI | CI exercises the `none` judge; the keyed and CLI judges are exercised when you run `probes/run.py judge_modes` with your own keys. | — |

---

| | |
|---|---|
| **What is where** | [`03_architecture.md`](03_architecture.md) |
| **Why the loop is shaped this way** | [`05_design_rationale.md`](05_design_rationale.md) |
| **Where it goes next** | [`09_future_states.md`](09_future_states.md) |
