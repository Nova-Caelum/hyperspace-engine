# Hyperspace Engine — working in this repository

You are in a checkout of the Hyperspace Engine plugin: a five-station development loop for Claude
Code with evidence-bearing gates, a local SQLite task graph, a local closure verifier and a
localhost console. This file is for an agent changing the engine itself. If you are *using* the loop
in your own project, the skills route you — start at `skills/acing-hyperspace/SKILL.md`, not here.

## Precedence

Code is truth. Skills own procedure. Docs own the machine.

- `bin/` and `hyperspace/` are authoritative about behaviour. When a document disagrees with them,
  the document is stale.
- `skills/` own what an agent does at each station. Nothing in `docs/` overrides a skill.
- `docs/` explains the machine. `docs/reference/` is generated from source and CI-checked.

## Where things are

| Path | What it is |
|---|---|
| `bin/` | The engine: run state (`loop_state.py`), gates (`node_gates.py`), endings (`loop_terminal.py`), run-folder map, plan lint, contract pre-check, MCP launcher |
| `hooks/` | The `SessionStart` hook (`hooks.json` + `session-start.sh` + `session_start.py`): primes `acing-hyperspace`, prints active-run status, bumps budget counters, surfaces recent worklog |
| `skills/` | Six loop skills and `hyperspace-setup` |
| `hyperspace/` | The runtime package: contracts, store, graph tools, verifier graph, judges, MCP server, loopback door, setup, CLI |
| `ui/` | The prebuilt console; `ui/SOURCE.md` pins the source commit |
| `probes/` | Acceptance probes that write verdict files |
| `tests/` | The pytest suite, including the drift test for `docs/reference/` |
| `docs/` | Understanding (numbered files) and reference (generated, plus the hand-written `tripwires.md`) |

The full component map is `docs/03_architecture.md`; what differs from the source engine is
`docs/06_adaptation_notes.md` and `bin/PORT_NOTES.md`.

## Rules for changing the engine

1. **Never hand-edit `loop.state.json` or `.hyperspace/graph.db`.** The state file is written only by
   the event verbs in `bin/loop_state.py`; the store only by the graph tools and the verifier. Their
   preconditions are the point.
2. **Read `docs/reference/gate-contracts.md` before touching a gate.** A gate checks evidence, never
   quality; the reasoning behind each rule is in `docs/05_design_rationale.md`.
3. **Regenerate the reference when you change a CLI flag, a state field, a status, a gate constant or
   an MCP tool:** `python docs/reference/generate.py`. `tests/test_reference_docs.py` fails otherwise.
4. **Keep the shipped tree neutral.** No personal names, private paths or references to the source
   system's infrastructure in `bin/`, `skills/`, `hyperspace/`, `ui/`, `probes/` or `tests/`. The
   scan probes enforce it:
   `python probes/run.py --out "$(mktemp -d)" --no-paid no_nova_infra no_vault_refs gear_names`
5. **Changes to the loop's rules come from the source engine, not from here.** This repository is a
   port. Record every port-only adaptation in `bin/PORT_NOTES.md` with its before, after and reason.
6. **Never write a `done` state directly.** A row closes through `complete_workitem`; a run ends
   through `confirm`, `descope` or `record-kill`.

## Running things

```bash
uv venv && uv pip install -e ".[dev]"
uv run python -m pytest tests/ -q
uv run python docs/reference/generate.py --check
claude plugin validate --strict .
```

Release tags: `hyperspace-engine--v<version>` (read by Claude Code's dependency resolver, created with
`claude plugin tag`) and `v<version>`, both on the released commit.
