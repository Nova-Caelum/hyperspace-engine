# 03 — Architecture

What is where, and what each piece is. This file draws the boundary lines — engine, skill, runtime,
console, test — so that when you open a file you know which part of the system you are standing in.

It describes the machine. It does not tell an agent how to run a stage; the skills own that. Exact
flags, fields, exit codes and tool arguments are in [`reference/`](reference/), which is generated
from source.

---

## 1. The whole system on one page

Hyperspace Engine is a Claude Code plugin. Installed, it adds six loop skills, one setup skill and one
MCP server to a session. Set up in a project, it keeps everything it owns inside that project: an
isolated Python environment, one SQLite file, one config file, and the run folders.

```
 Claude Code session ───────────────────────────────────────────────────────────────┐
 │  skills (acing-hyperspace, gear2 … gear6, hyperspace-setup)                     │
 │        │ call engine scripts                     │ call MCP tools              │
 │        ▼                                         ▼                             │
 │  bin/loop_state.py, node_gates.py …       MCP server `hyperspace` (stdio)      │
 │  (run state, gates)                       .hyperspace/env/bin/python           │
 │                                           -m hyperspace.mcp                    │
 └────────┬─────────────────────────────────────────┬─────────────────────────────┘
          │ writes                                  │ reads / writes
          ▼                                         ▼
 <project>/hyperspace/runs/<slug>/          <project>/.hyperspace/graph.db
   loop.state.json, DRIVE_MAP.md,             projects, modules, work_items,
   01_understand/ … build/                    filings, verifier_runs, …
                                                    ▲
                                                    │ reads (REST) / writes (JSON-RPC)
                                             loopback door 127.0.0.1:<port>
                                                    ▲
                                                    │
                                             browser: the task-graph console
```

Two stores of truth, kept apart on purpose:

| Store | Holds | Written by |
|---|---|---|
| `loop.state.json` (one per run) | Where the run is: node, status, gates passed, frozen artifacts, budget, ending | The event verbs in `bin/loop_state.py` |
| `.hyperspace/graph.db` (one per project) | What work exists and whether it is done: projects, modules, work items, filings, verifier runs | The graph tools and the verifier, through the MCP server or the door |

A run points at rows by `external_id`; the Build gate reads the rows back to reconcile them. Neither
store is ever edited by hand.

---

## 2. Plugin manifests

| File | Role |
|---|---|
| `.claude-plugin/plugin.json` | Plugin identity: name `hyperspace-engine`, version, licence, homepage. The version is what a dependent plugin's semver range resolves against. |
| `.claude-plugin/marketplace.json` | Makes the repository its own marketplace. The single entry has `source: "./"` — the repository root is the plugin. |
| `.mcp.json` | Registers one MCP server, `hyperspace`, whose command is the project's own interpreter, `${CLAUDE_PROJECT_DIR}/.hyperspace/env/bin/python`, with `-m hyperspace.mcp` — spawned directly, no shell, on every OS (the one path valid on macOS, Linux and Windows; see [`reference/tripwires.md`](reference/tripwires.md), "the `env/bin` contract"). |
| `hooks/hooks.json` | Registers one hook, `SessionStart`, with no `matcher` — it fires on every session-start source (`startup`, `resume`, `clear`, `compact`, `fork`), running `hooks/session-start.sh` (which hands its Python-shaped work to `hooks/session_start.py`). |
| `pyproject.toml` | The `hyperspace` Python package, its runtime dependencies, and the `hyperspace` console script. Requires Python 3.11 or newer. |

Releases are tagged `hyperspace-engine--v<version>` (the `claude plugin tag` convention, which Claude
Code's dependency resolver reads) and `v<version>`.

**The session-start hook** (`hooks/`) is what keeps the loop from going silent across a session
boundary. `hooks/session-start.sh` prints the `acing-hyperspace` primer (frontmatter stripped) on
every `SessionStart` and a setup-state line (never set up, or set up without an environment) — work
that needs no Python — then finds an interpreter (the project environment in either OS layout,
`python3`, `python`, `py -3`, each executed before it is trusted) and runs `hooks/session_start.py`:
one status line per active run under `hyperspace/runs/`, bumping the `fresh_sessions`/`compactions`
budget counters on `startup`/`compact` by calling `bin/loop_state.py`'s own `bump`/`notify` verbs, and
up to 5 recent rows from `.hyperspace/graph.db`'s `worklog` table when that database exists. POSIX
`sh` (Git Bash on Windows), fail-open, UTF-8 output, no dependency beyond the Python this plugin
already requires. What this replaces from the source engine's own session-start hook is in
[`06_adaptation_notes.md`](06_adaptation_notes.md) §7; the couplings its literal names create are in
[`reference/tripwires.md`](reference/tripwires.md).

---

## 3. The engine — `bin/`

The loop itself. Standard library plus one lazily imported contract; this is the part that decides
where a run is and whether it may move.

| File | What it is |
|---|---|
| `loop_state.py` | The run-state machine and its CLI: `init`, `read`, `set-node`, `gate-pass`, `check`, `record-kill`, `descope`, `confirm`, `bump`, `notify`, `record-approval`. The only writer of `loop.state.json`. |
| `loop_state.schema.json` | The state file's shape. Fields in [`reference/state-fields.md`](reference/state-fields.md). |
| `node_gates.py` | The exit checks, one per gated node, registered in `CHECKS`. Reads evidence; never writes state. Contracts in [`reference/gate-contracts.md`](reference/gate-contracts.md). |
| `loop_terminal.py` | The status vocabulary and the ending predicate. Values in [`reference/status-vocabulary.md`](reference/status-vocabulary.md). |
| `drive_map.py` | The run folder's schema and its generated `DRIVE_MAP.md`, rewritten at every node entry and gate. |
| `plan_lint.py` | A plan author's self-check. Not a gate. |
| `validate_candidate.py` | Validates a `tests.json` against the acceptance contract before the Understand gate runs. Shares the gate's contract loader, so the two cannot disagree. |
| `hyperspace_setup.py` | The setup skill's bootstrap: puts the plugin root on `sys.path` and runs the stdlib-only `hyperspace.setup` entry point, before `.hyperspace/env` exists. One command form for every shell. |
| `PORT_NOTES.md` | The ledger of every adaptation made when the engine was ported into this plugin. See [`06_adaptation_notes.md`](06_adaptation_notes.md). |

Skills call these scripts as `.hyperspace/env/bin/python "${CLAUDE_PLUGIN_ROOT}/bin/<script>.py"`.
Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}` into skill text, so the command resolves to the
installed copy; the interpreter is the project's isolated environment, never a global Python.

---

## 4. The skills — `skills/`

Procedure lives here and nowhere else.

| Skill | Role |
|---|---|
| `acing-hyperspace` | Session entry. Routes the work to the station it belongs in, from the run's state file. |
| `gear2-understand` · `gear3-decide` · `gear4-draft` · `gear5-build` · `gear6-live` | The five stations. Each is the only door into its stage; the node each maps to is in [`02_the_loop_and_gates.md`](02_the_loop_and_gates.md). |
| `hyperspace-setup` | One-time provisioning of a project: environment, store, judge, door, launcher. |

Each station directory holds `SKILL.md` and, behind it, `demi/` (steps inside the station, not
independently invocable) and `references/` (templates a demi depends on, such as
`gear2-understand/references/candidate-template.json` and `gear5-build/references/manual-review-template.md`).

---

## 5. The runtime package — `hyperspace/`

Everything that runs against the local store. Installed into the project's `.hyperspace/env` by the
setup skill, together with its dependencies (`pydantic`, `pydantic-graph`, `pydantic-ai-slim`, `mcp`).

| Package | What it is |
|---|---|
| `contracts/` | The acceptance contract (`candidate.py`: `CandidateWorkItem`, the criterion kinds, the specification) and the verifier's result types (`results.py`). One copy, shared by the Understand gate, the graph tools and the verifier. |
| `store/` | `Store` over one SQLite file (`schema.sql`). Tables: `meta`, `projects`, `modules`, `work_items`, `work_item_relations`, `cycles`, `cycle_assignments`, `initiatives`, `initiative_links`, `worklog`, `verifier_runs`, `filings`. `filings` is append-only. |
| `tools/` | The graph-tool table (`registry.py`): one `ToolSpec` per tool with the JSON schema both transports serve. `upsert_work_item` validates the contract and writes an immutable filing. |
| `verify/` | The closure verifier: `complete_workitem` as a `pydantic_graph` graph — `Vet → CriteriaQuality → Landing → EvidenceJudge → Commit`. Evidence is a delta since the row's filing. |
| `judge/` | The judge runners behind the verifier's two semantic steps: `openrouter`, `anthropic` (both through pydantic-ai), `claude-code`, `codex` (both through their CLIs), and `none`. |
| `mcp/` | The stdio MCP server. Lists `complete_workitem` plus every graph tool, answers against the store, and starts the loopback door on first use. |
| `http/` | The loopback door (`server.py`) and its routes (`routes.py`): REST reads under `/api/…`, JSON-RPC writes on `POST /mcp`, the console page on `/`. |
| `setup/` | Provisioning (`provision.py`), the stdlib-only bootstrap entrypoint (`python -m hyperspace.setup`), `doctor`, and the three launcher templates. |
| `cli.py` · `worklog_cli.py` · `config.py` | The `hyperspace` command (`init`, `serve`, `doctor`, `worklog`) and `.hyperspace/config.toml` (`judge`, `model`, `port`, `user`). |

The full tool list with arguments is [`reference/mcp-tools.md`](reference/mcp-tools.md); the commands
are in [`reference/cli.md`](reference/cli.md).

---

## 6. What lives in your project

Setup writes one hidden directory; the loop writes one visible one.

| Path | What it is |
|---|---|
| `.hyperspace/env/` | The isolated Python environment (created with `uv` when it is on `PATH`, otherwise `venv` + `pip`). The MCP launcher and every skill command use its interpreter. |
| `.hyperspace/graph.db` | The task graph. One file; copy it and you have copied every row, filing and verifier run. |
| `.hyperspace/config.toml` | `judge`, `model`, `port` (default 8791), `user` (the identity a manual attestation must carry, default `user`). |
| `.hyperspace/Open Hyperspace.command` · `.bat` · `open-hyperspace.sh` | The launcher for your platform. Opens the console without a Claude Code session. |
| `hyperspace/runs/<slug>/` | One folder per run: `loop.state.json`, `original_input.md`, `DRIVE_MAP.md`, one folder per station, `build/`, `BUILD_LEDGER.md`, `RECONCILIATION.md`, `misc/`. |

Nothing is written outside the project directory, and nothing in the project depends on a service
outside the machine.

---

## 7. The console — `ui/`

The task-graph console is Caelos, prebuilt and shipped as static files, so a user never needs Node.

| Path | What it is |
|---|---|
| `ui/dist/` | The built console: `index.html` and three assets. Served by the door. |
| `ui/SOURCE.md` | Provenance: the pinned Caelos commit, the build commands, and the build-time settings. |
| `ui/build.sh` | Rebuilds `ui/dist/` from a fresh clone of the pinned commit. CI runs the reproducibility check against it. |

Two build-time settings shape the bundle: `VITE_API_BASE_URL=.` makes every request same-origin, so
the same bundle works on any port the door binds; `VITE_HUMAN_OWNER=user` sets the owner the console
offers first when you assign a project.

---

## 8. How a row travels

The path one work item takes from filing to a `done` you can see in the browser:

| Step | Where | What happens |
|---|---|---|
| 1. File | `upsert_work_item` (MCP) | The candidate is validated against the contract; the row is written; an immutable filing records the criteria and the time. |
| 2. Work | Your project | Files change. |
| 3. Claim | `complete_workitem` (MCP) | The agent names every path it created, modified or deleted. There is no narrative field. |
| 4. Vet | Verifier | The row exists and is open; the criteria resolve from the filing; each touched path is present or absent as claimed. |
| 5. Criteria quality | Verifier, judge | Are the criteria about this task and observable? Skipped under `judge = "none"`. |
| 6. Landing | Verifier | Each deterministic criterion is checked against the delta since filing. Already true at filing never counts. |
| 7. Evidence judge | Verifier, judge | Does the change establish each criterion? Skipped under `judge = "none"`. |
| 8. Commit | Verifier → store | `done`, `refused`, `unverifiable` or `already_done`. On `done` the row's `completed_by` is `hyperspace-verifier`, and the run is recorded in `verifier_runs`. |
| 9. Read | Door → browser | The console reads `GET /api/work-items/<id>` and shows the row as done. |

A person can also mark a row done in the console; that closure is stamped `hyperspace-console`. Given
a graph snapshot, the Build gate accepts these two labels and refuses any other door by name.

---

## 9. Probes, tests and CI

| Path | What it is |
|---|---|
| `tests/` | The pytest suite: engine, store, tools, verifier, judges, door, MCP, setup, probes, and the drift test for `docs/reference/`. |
| `probes/` | Acceptance probes, one per acceptance test of the release. Each writes a verdict file with `result: PASS` or `FAIL` and its evidence. `run.py <name>…` runs them; `whole_path` and `consumable` exercise the published plugin end to end. |
| `.github/workflows/ci.yml` | On every push and pull request: install, `pytest tests/`, `claude plugin validate --strict .`, the scan probes (`no_nova_infra`, `no_vault_refs`, `gear_names`, `known_defects`, `pydantic_graph`), and the console reproducibility check. |
| `reference/` (repository root) | Two historical files kept for reading: the pre-port verifier shim and the pre-port gate test harness. Neither runs from this repository. Not to be confused with `docs/reference/`. |

---

## 10. Boundaries

| Part | Owns | Does not own |
|---|---|---|
| Engine (`bin/`) | Run state, gates, endings | Work items, closure, procedure |
| Skills (`skills/`) | What an agent does at each station | Any state; they call the engine and the tools |
| Runtime (`hyperspace/`) | The task graph, closure, judges, transports | Where a run is |
| Console (`ui/`) | Showing and editing the task graph | Anything the door does not serve |
| Probes and tests | Evidence that the rest does what it says | Behaviour |

Platform scope: macOS is verified end to end; macOS, Linux and Windows each run the full suite, the
installer and MCP probes, and the real Claude Code binary's own MCP spawn and SessionStart hook in CI
(`probes/probe_claude_runtime.py`). One interpreter path, `.hyperspace/env/bin/python`, serves every
OS: on Windows provisioning makes `env/bin` a junction to the venv's `Scripts\`. Windows needs Git for
Windows, because Claude Code runs plugin hooks through Git Bash there.

---

| | |
|---|---|
| **What changed from the source engine** | [`06_adaptation_notes.md`](06_adaptation_notes.md) |
| **The stations and their gates** | [`02_the_loop_and_gates.md`](02_the_loop_and_gates.md) |
| **Exact flags, fields and tools** | [`reference/`](reference/) — generated from source |
