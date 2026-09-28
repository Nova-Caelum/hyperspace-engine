# 07 — Troubleshooting

Keyed by the message you actually saw. Find your line, read what it means, do the thing.

This file is not for reading front to back.

---

## First: read the exit code

| Exit | Name | What it is telling you |
|---|---|---|
| `0` | Pass | Artifacts frozen. At the Build gate, `status` is now `live`. |
| `1` | **Refused** | Evidence is missing, inconsistent or unreadable. **Your work is not finished.** |
| `2` | **Usage** | Your *command* was wrong — an unregistered node, or a required flag not supplied. Your work may be fine. |
| `3` | **HOLD** | Build only. Your work is built and a human is needed. **This is not an error.** See §6. |

Exit 2 and exit 1 get confused constantly, and the distinction matters: **exit 2 means fix your
command line, exit 1 means fix your work.** If you are re-running a gate with slightly different flags
hoping for a different verdict, check which one you are getting.

Gates collect every cause they can before returning. If you see six lines, you have six things to fix,
and fixing one and re-running wastes a round.

---

## 1. Understand gate (`--node understanding`)

| Message | Means | Do |
|---|---|---|
| `tests file unreadable/not JSON: <path>` | The file is missing, is not JSON, or its top level is not an object. | Check the path is the one you think it is; run it through a JSON parser. A trailing comma is the usual culprit. |
| `cannot import the CandidateWorkItem contract from the plugin at <path>: <error>` | The gate could not load the schema it validates against. **This is an environment problem, not a problem with your tests file.** | Read the nested error. The gate refuses rather than validating against a stale second copy — `05_design_rationale.md` §9 explains why. |
| `cannot validate tests.json: pydantic is not installed in this interpreter — use the project's .hyperspace/env interpreter, or run: hyperspace doctor` | The gate is running under the wrong Python. Nothing is wrong with your tests file. | Do what it says: use the project's `.hyperspace/env` interpreter, or run `hyperspace doctor`, which re-runs the setup checks and tells you what is missing. |
| `tests.json fails the CandidateWorkItem contract: <error>` | Loaded and validated, and the contract rejected it. | Fix the field the nested error names. |
| *(the validator's own text)* | Your tests file loaded but does not satisfy the contract. The message is the validator's, verbatim, not a paraphrase. | Fix the field it names. The text is precise; read it literally rather than guessing at intent. |
| `C10: no machine-checkable criterion — an all-manual test set cannot pass its own N1 gate` | Every criterion you wrote needs a human to judge it, so nothing can ever discharge itself. | **Do not delete your manual criteria.** Add an executable one beside them — a command that exits 0, a file that must contain a string, an endpoint that must return a status. |
| `no WHOLE-PATH: criterion — at least one criterion must exercise the whole path from entry to finish` | Every criterion tests a part. Nothing tests the seam. | Add one criterion whose statement begins `WHOLE-PATH:` and which exercises entry to finish. A set of passing units routinely describes a system that does not work. |

There is **no hold path** at this gate. It passes or it refuses.

---

## 2. Decide gate (`--node deciding`)

| Message | Means | Do |
|---|---|---|
| `mapping file unreadable/not JSON: <path>` | `mapping.json` is missing or malformed. | As above. |
| `mapping missing key: <key>` | A required top-level key is absent. Every missing key is reported together. | Add them all, re-run once. |
| `tests file unreadable/not JSON: <path>` | The mapping points at a tests file the gate cannot read. Paths in `mapping.json` resolve **relative to the mapping file's own directory.** | Check the relative path. This is the most common cause of this line at this gate. |
| `mapping names no components` | The mapping parsed but declares nothing. | You have a design decision that has not been written down as components yet. |
| `component has no name` | A component entry is missing its name. | Name it. An unnamed component cannot be referenced by a test or deferred by name. |
| `duplicate component name: <name>` | Two components share a name. | Rename one. Ambiguous names make the mapping unverifiable. |
| `<name>: tests must be a list of test ids` · `<name>: principles must be a list of principle ids` | Type error — a string where a list was expected. | Wrap it in a list, even for one entry. |
| `<name>: unknown test id <id> (tests.json declares T1..T<n>)` | A component claims to satisfy a test that does not exist. | Usually a typo or a stale id from an earlier draft of the tests file. The frozen tests file is authoritative. |
| `<name>: unknown principle <id> — not in principles.json` | A component is justified by a principle the snapshot does not contain. | Either the principle is missing from the snapshot or the id is wrong. A component justified by a principle that does not exist is unjustified. |
| `T<n> maps to no component` | A frozen acceptance test has nothing that will satisfy it. | **This is the most important refusal at this gate.** Either add a component that addresses it, or deliberately defer it under `## Deferred`. Do not silently drop it — that is exactly what the check exists to prevent. |

There is **no hold path** at this gate.

---

## 3. Draft gate (`--node specifying`)

| Message | Means | Do |
|---|---|---|
| `plan file unreadable: <path>` | `Plan.md` is missing or cannot be read. | Check the path. |
| `plan declares no task blocks (no level-4 #### T<n>.<m> heading)` | The gate found no task blocks. Heading level and shape both matter: `####`, then `T<n>.<m>`. | Check you used four hashes, not three. |
| `<label>: no task_id field` | A task block has no `task_id` marker at all. | The filing step writes these. A block with no marker was not filed — **file it, do not hand-write an id.** |
| `<label>: task_id is blank — not backfilled by the uploader` | The marker exists, the value is empty. | Same: this row was never filed. The gate is checking that your plan's claim to have filed work is true. |
| `<label>: task_id <value> is not a UUID — not backfilled by the uploader` | Something is in the field, but it is not a filed row's id. | A placeholder, or a hand-typed value. Re-file; do not invent an id to satisfy the check. |

**Do not hand-edit `task_id`s to get past this gate.** It is the only proof the engine has that the
work was actually filed. Satisfying it manually removes the one check that catches a plan which was
written and never filed.

There is **no hold path** at this gate.

---

## 4. Build gate (`--node executing`)

Four evidence inputs: the workplan, the verifications directory, the reconciliation artifact, and
optionally a graph snapshot. Missing any required one is exit 2, not exit 1.

| Message | Means | Do |
|---|---|---|
| `workplan unreadable or invalid JSON: <path>` | The workplan could not be read. | Check the path and the JSON. |
| `reconciliation artifact unreadable: <path>` | Same for the reconciliation. | As above. |
| `graph snapshot unreadable or not a list of rows: <path>` | The snapshot is malformed, or is not a list. | The snapshot is optional — if you passed it, it must be well-formed. |
| `<external_id>: no disposition in reconciliation artifact <path>` | **A filed row is not mentioned in the reconciliation at all.** | Give it a disposition: `done`, `deferred`, `archived`, or `live-test`. This is the specific hole the gate exists to close — a row that looked done and was never closed. Silence about a row is the failure. |
| `<external_id>: no verifier run found under <dir>` | The row claims `done` but there is no verifier run file for it. | Close the row through the verifier. A `done` in the reconciliation is a claim, not a closure. |
| `<external_id>: verifier status is '<status>' in <file> — not done` | The verifier was run and did not return `done`. | Read the verifier's own output. `refused` tells you what to fix; `unverifiable` means it could not tell, and routes to a human. |
| `<external_id>: done with no completed_by and updated_at <ts> ... done in the task-graph console if you have confirmed it yourself` | The row reads `done` but carries no record of which door closed it. | Closure identity is part of the evidence; a row closed by nothing is not closed. Either close it through the verifier, or mark it done in the task-graph console — a deliberate human closure is a legitimate discharge and is labelled as one. |
| `node_gates: skipping unreadable verification file <path>: <error>` *(stderr)* | One file in the verifications directory could not be parsed. | This is a **refusal cause**, not a warning to scroll past. A check that cannot read its evidence has not passed. |

### Things that do *not* need a verifier run

`deferred` and `archived` rows pass without one — they are descoped, not built, so there is nothing to
verify. `live-test` also passes: its work cannot begin until the run is live, and it is the only
disposition permitted to cross the gate open.

### The one thing that will not work

**The reconciliation artifact cannot rescue a `done` row.** If you write `done` next to a row whose
verifier run says otherwise, the row refuses or holds exactly as it would have. Every undischarged
executable criterion — `command_check`, `file_state`, `db_readback`, `http_readback` — still counts.
Changing the disposition does not change the evidence.

---

## 4b. `init` refuses an occupied slug

> `a run already exists at <path> (<description of the existing run>). `init` writes a fresh document and
> would discard its trail, gates, artifacts and budget. Pick a different --goal slug for the new run
> (the folder's prose is unaffected), or pass --force to replace the state document on purpose.`

You pointed `init` at a goal slug that already holds a run. **This refusal is protecting a run's entire
history** — trail, gates, frozen artifact hashes, budget, `run_id`, and any recorded ending. Without it,
picking a goal back up silently resets the run to `framing`.

Do one of:

- **Pick a new slug.** The usual answer. The old run's prose and artifacts stay exactly where they are
  and become input to the new run, so nothing is redone.
- **`--force`**, only when you know the state document is corrupt and you mean to replace it. It mints a
  new `run_id` and discards the old record.

Reviving an ended run in place is deliberately hand-work — there is no `resume` verb, so a run cannot be
un-ended by accident.

## 5. Exit 2 — usage

| Situation | Fix |
|---|---|
| `gate-pass --node live` | Refused by design. `live` is a stage, not a gated node; only four nodes are registered. Nothing is gated there — the exit is the human's `confirm`. |
| An unregistered node name | Typo, or a node that has no check. Registered: `understanding`, `deciding`, `specifying`, `executing`. |
| A required evidence flag not supplied | The gate names the flag. Supply it; exit 2 is not a verdict on your work. |

---

## 6. Exit 3 — HOLD is not an error

You will see a list of rows, each with a criterion quoted.

**That list is your agenda with the human.** Every row on it is built work carrying a criterion only a
person can discharge. The gate is not blocking you; it is telling you that you have finished something
and have not yet asked anyone to look at it.

Do:

- Take the list to the human. Quote each criterion as written.
- Get each one attested, then re-run the gate.

Do not:

- Look for a way around it. There isn't one, by design.
- Reclassify the rows to something the verifier does not check. That is the artifact-as-self-certification
  path, and §4 explains why it fails.
- Treat it as blocked. An unreviewed row is not a blocked row — it is the agent failing to ask. The
  reasoning, including the decision this reversed, is in `05_design_rationale.md` §6.

---

## 7. Before you conclude the gate is wrong

In order, because each is cheaper than the next:

1. **Re-read the message literally.** These messages name the file, the id, and the cause. A guess at
   what it "probably means" is usually the reason a second run fails the same way.
2. **Check the exit code.** 2 is your command; 1 is your work. Re-running with new flags cannot fix a 1.
3. **Check every line.** Gates collect all causes at a level. Fixing one of six and re-running burns a
   round for nothing.
4. **Check path resolution.** Several artifacts reference others by paths relative to *their own*
   directory, not to the run root or your shell. This causes more spurious refusals than any other
   single thing.
5. **Check you are looking at the right run.** The state file is the authority on which node you are
   in. If the gate seems to be checking a stage you thought you had left, read the state file.
6. **Read the check's source.** `bin/node_gates.py` is the last word, and it is readable. The gate does
   exactly what it says and nothing else — it has no opinion about your work, so it is not being
   difficult.

If after all six the gate is refusing something that genuinely satisfies its stated contract, that is a
bug worth reporting, with the message and the artifact that produced it.

---

## 8. Setup, the environment, and Windows

Messages from the session preload (the `SessionStart` hook), `hyperspace doctor`, the launcher, and
Claude Code's own `/mcp` / `claude mcp list`. The same on macOS, Linux and Windows unless the row
says otherwise.

| Message | Means | Do |
|---|---|---|
| `No .hyperspace/ found in this project yet` | This project was never set up. | Say "set up hyperspace". |
| `The hyperspace MCP server cannot start: <path> is missing` | `.hyperspace/` exists but its environment does not — the server Claude Code starts is `.hyperspace/env/bin/python -m hyperspace.mcp`. `/mcp` shows it as `✘ Failed to connect` — `ENOENT … .hyperspace/env/bin/python` on macOS and Linux, `CONNECTION_CLOSED: Connection closed` on Windows. | Run the `hyperspace-setup` skill again, then restart the session. |
| `No Python 3.11+ found (tried the project environment, python3, python, py -3)` | The preload found no usable interpreter, so it skipped the active-run and worklog blocks. The primer still arrived. | Install Python 3.11+ (python.org — on Windows it adds the `py` launcher) or `uv`, then run setup. |
| `Python was not found; run without arguments to install from the Microsoft Store` *(Windows)* | `python` / `python3` is Windows' Store placeholder, not a Python. The preload and the setup skill both skip it. | Install Python from python.org (or `uv`); the placeholder can stay. |
| `found <path>, but <path> does not reach it — the env/bin junction is missing` *(Windows, `doctor`)* | The environment exists in Windows' own layout (`Scripts\python.exe`) but `.hyperspace/env/bin`, the path `.mcp.json` and the skills use, does not lead to it. | Re-run the `hyperspace-setup` skill. If it fails again, the project is on a drive that cannot hold a directory junction (exFAT/FAT32, some network shares) — move it to an NTFS drive. |
| `Hyperspace: .hyperspace\env\Scripts\hyperspace.exe is missing.` *(Windows launcher)* | `Open Hyperspace.bat` was run in a project whose environment is gone. | Run the `hyperspace-setup` skill in Claude Code for this project, then open the launcher again. |
| No preload at all — no primer, no status line — at session start *(Windows)* | Claude Code runs plugin hooks through Git Bash on Windows and falls back to PowerShell without it; this plugin's hook needs Git Bash. | Install Git for Windows. If it is installed somewhere unusual, set `CLAUDE_CODE_GIT_BASH_PATH` to its `bin\bash.exe`. |
| `port <n> is in use — pass --port <other> or set port in .hyperspace/config.toml` | Something already listens on the console port. `doctor` tells you whether it is this project's own door. | If it is ours, just open the URL. Otherwise pick another port. |

---

| | |
|---|---|
| **What each gate checks** | [`02_the_loop_and_gates.md`](02_the_loop_and_gates.md) |
| **Why it checks that** | [`05_design_rationale.md`](05_design_rationale.md) |
| **Exact flags and exit codes** | [`reference/`](reference/) — generated from source |
