---
name: demi-build-worktree
description: Demi-skill of gear5-build. Emits the row's isolation ruling — shared tree with file ownership, or a git worktree — recorded in the brief and the ledger.
disable-model-invocation: true
derives_from: using-git-worktrees
license: MIT
author: Nova Caelum
version: 1.0
---

# Build — Isolation Ruling

**Parent node:** `gear5-build`
**Invocable:** No. Reached only by its parent node, or dispatched to a subagent by it.
**Emits:** one `Isolation:` line in `build/<row>/brief.md` and one `Ruling:` line in `BUILD_LEDGER.md`

## Overview

Decides, per row and before dispatch, where the implementer's edits land — so two implementers never touch one file and no worktree ever lands inside the vault. The implementer inherits the ruling; it does not choose.

## Dispatch shape

### Context

- **Anchor docs (READ THESE FIRST):**
  - `<run-dir>/BUILD_LEDGER.md` — rows in flight and the files each owns
  - `<run-dir>/build/<row>/brief.md` — the row this ruling is for
  - `$VAULT_ROOT/.claude/rules/vault-hygiene.md` — no bulk trees, no duplicate folders inside the vault
  - `$AGENTOS_ROOT/system/README.md` — canonical layer; promote is `git-promote.sh` (`git add -A`) on the shared tree
- **Locked decisions — do NOT re-open:** D12 (vault repos → shared tree + file ownership; repos outside the vault → `Agent(isolation:"worktree")`); SR#12/SR#17 (canonical-only edits); vault-hygiene rules 1–2.
- **Loop state:** `loop.state.json` must read `current_node: executing`.

### Your task

Produce the isolation ruling for one row.

1. Detect existing isolation first: `GIT_DIR=$(cd "$(git rev-parse --git-dir)" && pwd -P)`; `GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" && pwd -P)`; `git rev-parse --show-superproject-working-tree` (a path here means submodule, not worktree). `GIT_DIR != GIT_COMMON` and not a submodule → already isolated: record the path and branch, skip to step 5.
2. Classify the repository: working tree under `$VAULT_ROOT/` (`_agentOS`, `AgentSecretBase`) → **shared tree**. Under `~/NovaCaelum_code/` or elsewhere → **worktree-eligible**.
3. Shared tree: list every path the implementer may create or modify; compare against the ledger's in-flight rows. Any overlap → the later row waits (serialize); never split one file between two implementers.
4. Worktree-eligible: dispatch with `Agent(isolation:"worktree")` — the native tool owns placement and cleanup. `git worktree add` only if no native tool exists, and only after `git check-ignore -q <dir>` succeeds for the target directory.
5. Name the clean-baseline command the implementer runs first (explicit test targets; bare `pytest` is forbidden in this vault — it spawns real inference). A red baseline is reported in the report file, not fixed in passing.
6. Write `Isolation: shared-tree | worktree — files: <paths> — baseline: <command>` into the brief; append `Ruling: isolation <row> — <choice> — <cost if wrong>` to the ledger.

**Acceptance:** the brief carries the `Isolation:` line; no two in-flight rows own the same path; no worktree path is under `$VAULT_ROOT/`.

### Out of scope

- Branches or worktrees for vault repos — owned by `git-promote.sh` on the shared tree.
- Adding `.claude/worktrees/` to `_agentOS/.gitignore` — open follow-up from D12, not this ruling's call.
- Dependency installs in a new workspace — vault-hygiene rule 1 inside the vault; outside it, only if the row's brief names them.

### Deliverable format

- **Writes:** the `Isolation:` line (brief) and the `Ruling:` line (ledger).
- **Returns:** those two lines verbatim, under 60 words.

### Escalate if

- Repository classification is ambiguous (symlinked path, nested repo) → ledger `Ruling: isolation <row> deferred — <why>`; do NOT dispatch the row.
- `Agent(isolation:"worktree")` fails, or the worktree lands under the vault root → return `BLOCKED` with the path; do NOT fall back to `git worktree add`.
- Two ready rows own the same path and the plan calls them parallel → serialize and ledger it; do NOT split ownership by line range.

## Self-review

- [ ] The ruling names concrete paths, not "the relevant files".
- [ ] No worktree path under `$VAULT_ROOT/`.
- [ ] The baseline command names explicit test files.

## Gate contribution

Nothing mechanical at the node's exit gate: isolation is enforced before dispatch, not verified at exit. It surfaces indirectly — an unexpected tree in `git status` at promote, or a verifier `refused` traceable to a file collision — and each such surfacing is a ledger finding, not a formatting problem.

## Quick Reference

| Situation | Action |
|---|---|
| `GIT_DIR != GIT_COMMON`, not a submodule | Already isolated — record path + branch, skip to baseline |
| In a submodule | Treat as a normal checkout |
| Repo under `$VAULT_ROOT/` | Shared tree + file-ownership list; never a worktree |
| Repo under `~/NovaCaelum_code/` or elsewhere | `Agent(isolation:"worktree")` |
| No native worktree tool | `git worktree add` only after `git check-ignore -q <dir>` succeeds |
| Two in-flight rows own one path | Serialize; never split a file |
| Baseline red | Report it in the report file; do not fix in passing |

## Source

- **Origin:** D12 (m4-loop/DECISIONS.md, 2026-09-07) — `.claude/worktrees/` verified not ignored in `_agentOS`; `git-promote.sh` stages everything.
- **Precedent failures:** vault-nuke incident (~1 week lost; `vault-hygiene.md`); duplicate-folder drift, governance sprint; M4 Step 0 ran two engineers on a shared tree with the D1 ownership list and no collisions.
- **Authored by:** chief-pm on 2026-09-07.
- **Community lineage:** obra/superpowers `using-git-worktrees` 6.3.0 (MIT), archived at `01_research/upstream-source-6.3.0/skills/using-git-worktrees/SKILL.md`; ported: detect-first, native-tool-first, `check-ignore` guard, clean baseline; not ported: consent prompt, dependency auto-install, `.worktrees/` default.
- **Related:** `demi-build-subagent-dispatch`, `vault-hygiene` rule.
