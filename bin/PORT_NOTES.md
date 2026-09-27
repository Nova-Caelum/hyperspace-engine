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

## Kept deliberately (would change a rule)

- `node_gates.py` closure labels `graph-machine-committer` and
  `caelos-console`: the Build gate accepts a `done` row by matching them. They
  change only when the local store decides which labels it writes.

## Referenced, not shipped

The skills name these; the plugin does not carry them yet. Paths were rewritten
to the plugin form (§1) without changing the step:

- scripts: `bin/taskgraph_emit.py` (N3 emit), `bin/validate_candidate.py`
  (N1 pre-gate validator), `bin/template_lint.py` (section-shape lint);
- templates: `problem`, `decision`, `prd`, `plan` and demi-skill templates;
- skills: `taskgraph-write`, `taskgraph-placement`, `taskgraph-closure`,
  `assumption-check`, `overbloat-review`;
- MCP tool: `list_initiatives` (not in the graph-tools list).
