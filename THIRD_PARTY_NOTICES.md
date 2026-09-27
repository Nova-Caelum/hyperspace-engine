# Third-party notices

## Nova Caelum graph_library — the closure verifier

`hyperspace/verify/`, `hyperspace/judge/judgments.py`, `hyperspace/verify/prompts/`
and `hyperspace/contracts/results.py` are vendored from the Nova Caelum
`graph_library` (the canonical five-step `complete_workitem` verifier), 2026-09-26.
Each vendored Python file carries a two-line provenance header naming its source path.

| Product file | Source |
|---|---|
| `hyperspace/verify/claim.py` | `primitives/completion/claim.py` |
| `hyperspace/verify/compose.py` | `primitives/completion/compose.py` |
| `hyperspace/verify/delta.py` | `primitives/completion/delta.py` |
| `hyperspace/verify/landing.py` | `primitives/completion/landing.py` |
| `hyperspace/verify/predicates.py` | `primitives/verifier/__init__.py` |
| `hyperspace/verify/graph.py` | `primitives/completion/pipeline.py` (+ `render_observation` from `primitives/judges/semantics_agent.py`) |
| `hyperspace/verify/deps.py` | `primitives/completion/{pipeline,resolve}.py`, `contracts/commit.py::criteria_fingerprint` |
| `hyperspace/verify/prompts/{criteria,evidence}_judge.md` | `primitives/judges/prompts/` (verbatim; no vault-specific sentence found) |
| `hyperspace/judge/judgments.py` | `primitives/judges/judgments.py` (verbatim) |
| `hyperspace/contracts/results.py` | `contracts/results.py` (`CriterionVerdict`, `VerificationResult` only) |

### Adaptations

- **Graph, not function.** `complete_workitem` is a `pydantic_graph` graph of five `BaseNode`s — `Vet → CriteriaQuality → Landing → EvidenceJudge → Commit` (canonical order 1 → 3 → 4 → 2 → 5); each node body is the canonical block, moved. Built with pydantic-graph's `GraphBuilder` (the installed 2.51 API; `Graph(nodes=...)` no longer exists).
- **Backend: ops server → local store.** `Deps` keeps the canonical field names and adds `project_root`, `user_identity`, `judge_name`. `read_row` → `Store.get_work_item`; `resolve_criteria` → `Store.resolve_criteria(ref)` on the row's `graph://filing/...` ref; `commit` → `Store.set_work_item_state(id, "done", completed_by=...)`; `readback_state` → the row's `state`. `OpsClient`/`OpsError`, both bearer identities, `GMWORKER_*`/`GMCOMMITTER_*` and `bws` are not vendored; `BackendError` replaces `OpsError`.
- **`read_row` / `readback_state` take the claim's project** as a second argument (external ids are unique per project in the local store); a bare fallback lookup keeps the canonical project-mismatch refusal reachable.
- **`filed_at` is the FILING's timestamp**, not the row's `created_at`: a criteria update mints a new filing and the delta window restarts from it.
- **`vault_root` → `project_root`** (the directory holding `.hyperspace/`). Touched paths and criterion paths resolve against it; `~` and absolute touched paths still allowed. `resolve_touched_path` keeps the canonical behaviour (no touched-path traversal ban; the contract already refuses `..` on criterion paths).
- **Attestation identity:** `attested_by == "daniel"` → `attested_by == Deps.user_identity` (default `"user"`, else `.hyperspace/config.toml` `user = "..."`). The `manual` binding is otherwise ported as is: unattested is `uncertain`, never a silent pass.
- **Committer identity:** `graph-machine-committer` → `hyperspace-verifier` (written to the row's `completed_by`).
- **State writer:** the JSON-file `StateWriter` (home-directory default) → `StoreStateWriter`, which upserts the run's `verifier_runs` row at every junction; the whole `VerificationState` (trail, steps, final result) is stored in its `steps` column, `judge` records the runner name. Store errors are swallowed as the canonical writer swallowed `OSError`; an unknown project is recorded with `project_code = NULL`.
- **Interpreter selection for `command_check`:** the `~/NovaCaelum_code/<dir>-venv` sibling convention is dropped; a co-located `.venv` is still preferred over `sys.executable`.
- **Judges:** the pydantic-ai judge calls are not vendored. `hyperspace/judge/base.py` defines the `Judge` protocol (`judge_criteria`, `judge_evidence`, each returning the judgment and a usage dict) and `JudgeUnavailable`; judge errors get one retry, then `uncertain`.
- **The `none` ruling (the one intended behavioural divergence):** when `Deps.judge_name == "none"`, `CriteriaQuality` and `EvidenceJudge` record `skipped` ("no judge configured") without calling the judge, decided before any judge call. `compose()` is unchanged — it already passes `skipped` through — so the row closes `done` iff Landing discharged every criterion, and `unverifiable` if Landing left any criterion `uncertain`. Keyless closure of deterministic criteria. Under any other judge the semantic steps run exactly as canonical.
- **Text neutralised:** personal names and vault paths in docstrings/comments replaced with product terms (`claim.py`, `compose.py`, `landing.py`, one comment in `delta.py`); `results.py` drops `AttemptResult` and `RouteDecision` (the attempter/adjudication graph is deferred).
