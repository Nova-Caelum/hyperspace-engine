# Port notes — engine scripts and skills

This repo carries a port of the loop engine. The canonical engine lives in the
authors' private workspace; direction is **canonical → port only**. Every change
below is an adaptation the installable plugin needs (plugin-root resolution,
neutral wording, a vendored contract). None changes a rule, a gate, an exit code
or the freeze semantics. Port date: 2026-09-26.

The terms `probes/scan_tree.py` refuses under `bin/`, `skills/` and `hyperspace/`
are listed in `probes/check_port_scan.py` (`FORBIDDEN_TERMS`); this file names
them only by description so that it passes the same scan.

## 1. Script paths

- **Before:** `python3 $<CANONICAL_ROOT>/system/bin/<x>.py …` (an environment
  variable pointing at the authors' canonical layer), and bare
  `<canonical-layer>/system/bin/<x>.py` mentions.
- **After:** `.hyperspace/env/bin/python "${CLAUDE_PLUGIN_ROOT}/bin/<x>.py" …`
  in commands; `bin/<x>.py` in prose.
- **Why:** an installed plugin has no canonical layer. Claude Code substitutes
  `${CLAUDE_PLUGIN_ROOT}` into a plugin skill's text, so the command resolves to
  the installed copy of the script.

## 2. Interpreter convention

- **Before:** `python3` (whatever the shell finds).
- **After:** `.hyperspace/env/bin/python` — the project's isolated environment,
  provisioned by the setup skill. Each gear skill states this once, in the
  paragraph after its exit gate that defines `${CLAUDE_PLUGIN_ROOT}`.
- **Why:** the Understand gate needs `pydantic`; the plugin never installs into a
  global interpreter.

## 3. Run-folder anchor

- **Before:** runs opened under the authors' private workspace folder.
- **After:** runs live under `<project>/hyperspace/runs/<slug>/` — stated once in
  `acing-hyperspace` and once in `gear2-understand`; elsewhere "the run folder".
- **Why:** the product runs in the user's own project.

## 4. Contract vendoring and field renames

- **Before:** `node_gates.py` put the canonical layer (an env var, else
  `Path.home()`-derived fallback) on `sys.path` and imported
  `graph_library.contracts.candidate`.
- **After:** `hyperspace/contracts/{candidate,enums}.py` vendored with a
  two-line provenance header; `node_gates.py` imports
  `hyperspace.contracts.candidate`, inserting the plugin root
  (`Path(__file__).resolve().parents[1]`) on `sys.path` only when `hyperspace`
  is not importable. Still lazy, inside the Understand check. A missing
  `pydantic` refuses with one line naming the fix — never a traceback.
- **Field renames:** the two founder-named "stated" fields →
  `user_stated_type`, `user_stated_action` (same types, same meaning).
- **Docstring wording:** references to the private workspace, the founder, the
  ops server and its hosting became neutral ("the graph service", "the user's
  working tree", "the author").
- **Not vendored:** `results.py` and every other `graph_library` module — later
  rows own them. `candidate.py` imports only `pydantic`, stdlib and `.enums`.

## 5. S1 — measured-only budget fields

- **Before:** the budget block wrote four caps — fresh sessions, compactions,
  real-time hours, worklog entries — each carrying `_is_measured: false` and an
  `_is_detected` flag; two of them were never counted by anything.
- **After:** only `fresh_sessions` and `compactions` (`{cap, used}`), which the
  SessionStart hook bumps. The two uncounted caps and both annotation keys are
  gone from `loop_state.py` and `loop_state.schema.json`. `bump`, `notify`,
  `check_frozen` and every other verb behave as before on the fields that remain.
- **Why:** a field that asserts a measurement nobody makes is a lie in the
  schema; dropping it beats labelling it.

## 6. Tool naming

- **Before:** fully prefixed MCP tool names for the ops server and the verifier
  server.
- **After:** "the `hyperspace` MCP server's `<tool>` tool" (`list_initiatives`,
  `complete_workitem`, and the same names for every other graph tool).
- **Why:** the prefix Claude Code assigns to a plugin-hosted server is not yet
  verified; the MCP row settles it.

## 7. Founder, vault and provenance wording

- **Before:** the founder's name wherever the text meant the human driving the
  loop; paths to private incident files, prior-run artifacts, internal
  decision/baseline records, a research archive and internal build ledgers;
  internal persona names.
- **After:** "the user" (with they/their) where the text means the human
  driving the loop; quoted rulings and lessons kept verbatim and attributed to
  "the author" or "a prior run"; private citations became neutral provenance
  ("an internal incident record (INC014, 2026-06-21)") — date kept, path
  dropped. The private shared-workspace root became `$WORKSPACE_ROOT` in the
  worktree demi. The review-signal header line became `**User reviewed:** no`.
- **Unchanged:** every skill's frontmatter `name:`; the six gear directory
  names; the gear skills' rules, gates, exit codes and ceremony.

## 8. Verifications directory

- **Before:** the Build gate defaulted to a hard-coded home-directory path for
  the verifier's run files.
- **After:** default `<run-dir>/misc/verifications/`
  (`node_gates.VERIFICATIONS_SUBDIR`, resolved by `loop_state.py gate-pass`
  against the state file's folder); `--verifications-dir` still overrides.
- **Why:** no machine-specific path; the run folder already has `misc/`.

## Canonical fixes ported

Both landed in the canonical engine on 2026-09-26; this copy predated them.

1. **`descope()` and `record_kill()` mirror `final_route` into `status`** —
   one line each. Without it a descoped or killed run kept a live status, stayed
   on the SessionStart banner and kept bumping counters.
2. **`LoopState.init()` refuses an occupied goal slug** — raises
   `FileExistsError` naming the existing run's `run_id`, `status` and
   `final_route`; `--force` (CLI) / `force=True` is the explicit override.
   The CLI surfaces the exception as a non-zero exit, as the canonical does.

Nine regression tests ported into `tests/test_loop_state.py`
(`InitDoesNotClobberTests`, six; `TerminalStatusMirrorTests`, three).

## Fix pass — controller rulings (2026-09-26)

### 9. N3 filing through the graph tools
- **Before:** `demi-draft-taskgraph-emit` mapped the plan to `workplan.json` and ran a
  batch uploader script (`validate` / `plan` / `apply`), which filed the rows and wrote
  the identifiers back into the Plan.
- **After:** the plugin does not ship an uploader. The demi still writes
  `03_draft/workplan.json` (the gate freezes it; the Build gate reads its
  `external_id`s), then calls the `hyperspace` MCP server once per object —
  `upsert_module` per module, `upsert_work_item` once per `####` task block,
  `get_work_item` to read each row back, `link_work_items` per dependency edge — and
  the agent writes each returned row `id` into that block's `task_id` by hand.
  `check_specifying`'s reading of `task_id` is unchanged. Authority: the plugin PRD's
  data flow, step 3.

### 10. `bin/validate_candidate.py` shipped
- The N1 pre-gate validator: loads a `tests.json`, strips `_`-prefixed keys at every
  depth, validates it as `hyperspace.contracts.candidate.CandidateWorkItem`. Exit 0
  prints `VALID`; exit 1 prints `INVALID` and pydantic's message; exit 2 when the file
  is unreadable or the contract cannot load (the code the N1 demi already names as
  `BLOCKED`). It reuses `node_gates.py`'s contract loader and annotation strip, so the
  validator and the gate cannot disagree. Test: `tests/test_port.py`
  `test_validate_candidate_script`.
- `skills/gear2-understand/references/candidate-template.json` shipped with it: the
  N1 test-writing demi's step 2 copies it, so it is a dependency, not a pointer. It is
  the source engine's template with neutral values and the renamed `user_stated_*`
  fields; the same test validates it.

### 11. Templates and the section-shape lint — per-reference decisions
No gate reads a template: the shape lint was never wired into any node check. So each
reference was replaced by a one-line statement of the section list, checked by the
demi's Self-review:
- `problem` template (`demi-understand-problem-depth`) → the seven `Problem.md`
  sections in order, stated inline.
- `decision` template (`demi-decide-architecture-sketch`,
  `demi-decide-option-generation`) → the five `Decision.md` sections in order.
- `prd` template (`demi-draft-prd-writing`) → the eight `PRD.md` sections in order.
- `plan` template (`demi-draft-plan-writing`) → its one required section, `## Files`.
- demi-skill template (`demi-draft-taskgraph-emit` header comment) → dropped; it only
  documented the file's own authoring template.
- The section-shape lint script → not shipped; no reference remains.

### 12. Helper skills not shipped — behaviour inlined
- **Contract rules** (was the task-graph write skill): required keys, placeholder
  refusal, ≥1 non-`manual` criterion, project-relative paths, the four filing tokens,
  no `exists` on a present path — inline in `demi-understand-test-writing`,
  `demi-draft-plan-writing` and `demi-draft-taskgraph-emit`.
- **Placement** (was the placement skill): module if other work items hang off it as
  independent deliverables, work item otherwise, `parent_work_item` for a step inside
  one — inline in the test-writing and emit demis.
- **Closure** (was the closure skill): the gate-block lines read "row closure", and a
  row closes only through the `hyperspace` server's `complete_workitem`.
- **Assumptions register** (was the assumption-check skill): list, rate confidence and
  load, verify low-confidence load-bearing rows by docs then a minimal test, record the
  five-column table — inline in `demi-understand-problem-depth` and
  `demi-decide-option-generation`.
- **Overbloat review** (was the overbloat-review skill): the five advisory tags
  (`redundant:`, `dormant-risk:`, `native:`, `yagni:`, `shrink:`), one finding per
  line, a score line — defined in `demi-decide-ruthless-descoping` step 2; the node and
  its other demis refer to "the overbloat review".
- **Evidence before closure** (was the completion-verification skill): each gate block's
  evidence line reads "evidence before closure: …"; at Build, the row's RED/GREEN run
  in its report is the per-task evidence required before `complete_workitem`.
- Provenance citations of those skills became neutral text ("a prior run's filing
  record, 2026-08-27"). `derives_from` of the test-writing demi is now `none`.

### 13. Closure labels
- **Before:** the Build gate accepted `done` rows stamped by the source engine's
  committer and console labels.
- **After:** `_COMMITTER_LABEL = "hyperspace-verifier"`,
  `_CONSOLE_LABEL = "hyperspace-console"` — the labels the local verifier and the
  console door write. Test: `test_build_gate_accepts_the_plugins_closure_labels` (the
  old committer label now refuses).

### 14. Still named, not shipped
- MCP tool `list_initiatives` (gear3 descoping) — being added to the graph tools by
  another row; the mention stays as the `hyperspace` server's `list_initiatives` tool.
