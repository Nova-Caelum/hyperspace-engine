# Vendored from the Nova Caelum graph_library primitives/verifier/__init__.py, 2026-09-26.
# Adapted for hyperspace-engine; see THIRD_PARTY_NOTICES.md.
"""`IndependentVerifier` — predicates against the world (§8.1, §9 node 6).

**The transcript is not a parameter.** `verify()` has no argument through which
an attempt transcript could arrive, and that is the point: §9 node 6's boundary
is an authorization boundary, and an authorization boundary enforced by
discipline is enforced until the first person in a hurry. A verdict that would
change if the transcript were removed is a verdict the transcript produced, and
the attempter is the one party with an incentive to describe a success it did
not achieve.

Two rules that make a pass mean something:

* **Zero discharged predicates is NOT a pass.** §9 node 6, verbatim: it is
  `failed_uncertain`. Vacuous truth is the most dangerous pass a verification
  suite can produce, because it is indistinguishable from a real one everywhere
  except here.
* **A `manual` criterion is left explicitly UNDISCHARGED** and passed to node 7
  or a human. Treating it as satisfied because the executable criteria passed is
  how a visual regression ships behind a green suite.

**Dispatch is from the run record's typed criteria, never from a filed row's
string** (§9). The row string is a truncated human digest by construction; a
verifier re-reading the row on a >2000-character criteria set is reading an
incomplete copy and would report a pass on whatever survived truncation.

**Readback caveat (§8.1), and it is not hypothetical.** `description` sits in
`_HEAVY_FIELDS` and is absent from every default read. Any predicate comparing a
filed row's specification MUST pass `include_heavy=true` or query SQL directly —
without it the readback sees `description: null` on a row that has one and
reports a false negative. The console drawer silently saved empty over stored
descriptions for months on exactly this defect.

Named consumers (§8's ≥2 rule):
  1. Graph Machine `verify_deterministic` + `verify_semantic` nodes — this PRD.
  2. The session-end verification hook — separate governance-sprint item.
  3. The `completed_work` reviewer, T7's companion — separate sprint item.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import sys

from ..contracts.results import CriterionVerdict, VerificationResult


@dataclass
class EvidenceContext:
    """Everything a predicate may read. Note what is ABSENT.

    There is no `transcript` field. Adding one would make the node-6 boundary a
    convention again — the whole reason this is a dataclass rather than a dict is
    that a dict would let one slip in without anybody editing this docstring.

    **`repo` (RootCause_B9_VerifierDischarge_CTO_2026-08-28 / ADR D3).** The
    per-run worktree in `workspace` is created empty and never populated with a
    checkout — every project-relative `file_state` criterion was undischargeable
    by construction, regardless of whether the asserted fact was true (B9).
    `repo` is the explicit, configurable, READ-ONLY evidence root `_file_state`
    consults after `workspace` comes up empty — the plane split D3 names: the
    worktree is the mutation plane (reversible, sacrosanct, unchanged), `repo`
    is the evidence plane (read-only, never written by any predicate here).
    `None` (the default) is byte-identical to pre-fix behavior — single-root,
    workspace-only resolution. No caller that omits it sees any change.
    """

    workspace: Path
    repo: Path | None = None
    # Code-owned registries. A proposer selects a KEY; it never supplies the
    # query, the URL, or the command. These dicts are the allowlist, and they are
    # the entire reason §15.2's "no raw shell/SQL/URL predicates" holds.
    db_queries: dict[str, Callable[[], Any]] = field(default_factory=dict)
    http_endpoints: dict[str, Callable[[], int]] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PredicateResult:
    satisfied: bool
    evidence: str
    uncertain: bool = False


class Predicate(Protocol):
    def evaluate(self, ctx: EvidenceContext) -> PredicateResult: ...


# ─────────────────────────────────────────────────────────────────────────────
# The code-owned dispatch registry (§9 node 6)
# ─────────────────────────────────────────────────────────────────────────────

_COMMANDS: dict[str, list[str]] = {
    "tests": [sys.executable, "-m", "pytest", "-q"],
    "typecheck": [sys.executable, "-m", "mypy", "."],
    "build": ["make", "build"],
    "lint": [sys.executable, "-m", "ruff", "check", "."],
    # git_diff_nonempty is handled structurally below, not as a shell command.
    #
    # The Python entries dispatch through `sys.executable`, never a bare
    # "python3" — that string resolves off PATH to whatever interpreter is
    # first on it, which may lack the verifier's own dependencies
    # (no `pydantic_ai`). `sys.executable` is the interpreter THIS verifier
    # process is already running under, so it always has what the check
    # needs. Regression: graph_library/tests/test_completion_core.py
    # (test_python_commands_dispatch_through_sys_executable).
}


def _run_command(check_id: str, target: str | None, ctx: EvidenceContext) -> PredicateResult:
    if check_id == "git_diff_nonempty":
        repo = ctx.repo or ctx.workspace
        proc = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True,
        )
        changed = [l for l in proc.stdout.splitlines() if l.strip()]
        return PredicateResult(
            satisfied=bool(changed),
            evidence=f"git status --porcelain: {len(changed)} changed path(s)",
        )

    argv = _COMMANDS.get(check_id)
    if argv is None:
        # Unknown checks are REJECTED or routed to manual — never executed by
        # default. An unknown key that fell through to a shell would be the
        # allowlist with extra steps.
        return PredicateResult(
            satisfied=False,
            evidence=f"check_id {check_id!r} is not in the code-owned registry",
            uncertain=True,
        )

    cwd = ctx.workspace
    # `target` SCOPES the check; it is never concatenated into a command string.
    # It is appended as a single argv element, so a shell metacharacter inside it
    # is an argument, not syntax — and the contract refuses those anyway.
    if target:
        argv = [*argv, target]
    proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True)
    return PredicateResult(
        satisfied=proc.returncode == 0,
        evidence=f"`{' '.join(argv)}` exited {proc.returncode}",
    )


def _resolve_in_root(rel_path: str, root: Path) -> Path | None:
    """Resolve `rel_path` against `root`; `None` if the result escapes `root`.

    Post-resolution containment check — the string-level guard (contract §15.2)
    blocks a literal `..`, but only this catches a symlink planted under `root`
    that resolves outside it. Called once per configured root (B9 fix, D3):
    two roots now means two independent containment checks, not one shared one.
    """
    candidate = (root / rel_path).resolve()
    root_resolved = root.resolve()
    if root_resolved not in candidate.parents and candidate != root_resolved:
        return None
    return candidate


def _git_or_mtime(path: Path, root: Path) -> datetime | None:
    """Last-touched timestamp for `path`, preferring `git log` over raw mtime.

    A fresh checkout stamps every file with checkout time, not edit time — a
    `modified_after` built on raw mtime alone would read TRUE for every
    tracked file in a repo that was just cloned, regardless of when it was
    actually last edited. `git log -1` reports the commit that touched the
    path; mtime is the fallback for an untracked file or a root that is not a
    git repo at all (`git` exits non-zero, caught below).
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%aI", "--", str(rel)],
            capture_output=True, text=True, timeout=10,
        )
        ts = proc.stdout.strip()
        if proc.returncode == 0 and ts:
            return datetime.fromisoformat(ts)
    except (OSError, ValueError):
        pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _glob_exists(v: Any, ctx: EvidenceContext) -> PredicateResult:
    """`glob_exists` — `v.path` is a GLOB PATTERN, not a literal path.

    For an output whose exact name is not knowable at filing time (a run-id
    or a timestamp an attempt will generate), a literal `exists` check is the
    wrong predicate by construction — `glob_exists` names "did something
    matching this shape land" instead. Same workspace-then-repo resolution
    order as `_file_state`'s literal-path assertions; traversal is already
    refused at the contract layer (`FileStateCheck.path`'s `no_traversal`), so
    this only has to keep a matched result anchored inside the root it
    matched from (guards a symlink planted under the root pointing outside it
    — the same class `_resolve_in_root` guards for literal paths).
    """
    roots: list[tuple[str, Path]] = [("workspace", ctx.workspace)]
    if ctx.repo is not None:
        roots.append(("repo", ctx.repo))

    for name, root in roots:
        root_resolved = root.resolve()
        try:
            matches = list(root.glob(v.path))
        except (ValueError, NotImplementedError, OSError):
            continue
        contained = [
            m for m in matches
            if root_resolved in m.resolve().parents or m.resolve() == root_resolved
        ]
        if contained:
            return PredicateResult(True, f"glob {v.path!r} matched {len(contained)} path(s) in {name}")
    return PredicateResult(False, f"glob {v.path!r} matched nothing in any consulted root")


def _file_state(v: Any, ctx: EvidenceContext) -> PredicateResult:
    """Resolution order: worktree first, then the evidence root (RootCause_B9 §4
    item 2 / ADR D3). The worktree holds what THIS run produced; the evidence
    root (when configured) holds claims about the world the run did not write.

    `ctx.repo is None` (the default) degrades to exactly today's single-root
    behavior — no caller that omits `repo` sees any change (root cause fix
    item 3: "safe default, no silent widening").

    `not_exists` is the one assertion where first-match-wins is unsound: an
    empty workspace satisfies it vacuously while the file exists in the
    evidence root, which would be a false pass from checking the wrong root
    first. It is checked against every configured root and must hold in ALL
    of them to discharge.

    `glob_exists` dispatches out immediately — `v.path` is a pattern, not a
    literal path, so the literal-path resolution below does not apply to it.
    """
    if v.assertion == "glob_exists":
        return _glob_exists(v, ctx)

    roots: list[tuple[str, Path]] = [("workspace", ctx.workspace)]
    if ctx.repo is not None:
        roots.append(("repo", ctx.repo))
    roots_by_name = dict(roots)

    resolved = [(name, _resolve_in_root(v.path, root)) for name, root in roots]

    # A path that escapes ANY consulted root is a hard stop — belt to the
    # contract's braces, and maximally cautious beats partial-escape ambiguity
    # about which root's containment failure should "count".
    escaped = [name for name, p in resolved if p is None]
    if escaped:
        return PredicateResult(
            False, f"path escapes the {'/'.join(escaped)} root: {v.path}", uncertain=True
        )
    paths: list[tuple[str, Path]] = [(name, p) for name, p in resolved if p is not None]

    if v.assertion == "not_exists":
        present = [name for name, p in paths if p.exists()]
        if present:
            return PredicateResult(False, f"{v.path} exists in {', '.join(present)}")
        return PredicateResult(True, f"{v.path} absent in {', '.join(n for n, _ in paths)}")

    for name, path in paths:
        if not path.exists():
            continue
        if v.assertion == "exists":
            return PredicateResult(True, f"{v.path} exists in {name}")
        if v.assertion == "modified_after":
            if not v.expected:
                return PredicateResult(
                    False, "modified_after requires `expected` (a reference timestamp) "
                    "and none was bound", uncertain=True,
                )
            try:
                reference = datetime.fromisoformat(v.expected)
            except ValueError:
                return PredicateResult(
                    False, f"expected {v.expected!r} is not a parseable ISO 8601 timestamp",
                    uncertain=True,
                )
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=timezone.utc)
            touched = _git_or_mtime(path, roots_by_name[name])
            if touched is None:
                return PredicateResult(
                    False, f"{v.path} in {name}: could not determine a modification time",
                    uncertain=True,
                )
            return PredicateResult(
                touched > reference,
                f"{v.path} in {name}: last touched {touched.isoformat()}, "
                f"reference {reference.isoformat()}",
            )
        text = path.read_text(encoding="utf-8", errors="replace")
        if v.assertion == "contains":
            hit = (v.expected or "") in text
            return PredicateResult(hit, f"{v.path} in {name} contains expected={hit}")
        if v.assertion == "hash_equals":
            import hashlib

            got = hashlib.sha256(text.encode()).hexdigest()
            return PredicateResult(got == v.expected, f"{v.path} in {name} sha256={got[:16]}…")
        return PredicateResult(False, f"unknown assertion {v.assertion!r}", uncertain=True)

    # Present in none of the consulted roots.
    if v.assertion in ("exists", "modified_after"):
        return PredicateResult(False, f"{v.path} exists=False in any consulted root")
    return PredicateResult(False, f"{v.path} does not exist in any consulted root")


def _db_readback(v: Any, ctx: EvidenceContext) -> PredicateResult:
    fn = ctx.db_queries.get(v.query_id)
    if fn is None:
        return PredicateResult(
            False, f"query_id {v.query_id!r} is not in the allowlist", uncertain=True
        )
    got = fn()
    ok = all(got.get(k) == val for k, val in (v.expected or {}).items()) if isinstance(got, dict) else got == v.expected
    return PredicateResult(bool(ok), f"db_readback {v.query_id}: {str(got)[:200]}")


def _http_readback(v: Any, ctx: EvidenceContext) -> PredicateResult:
    fn = ctx.http_endpoints.get(v.endpoint_id)
    if fn is None:
        return PredicateResult(
            False, f"endpoint_id {v.endpoint_id!r} is not in the allowlist", uncertain=True
        )
    status = fn()
    return PredicateResult(
        status == v.expected_status,
        f"http_readback {v.endpoint_id}: status {status}, expected {v.expected_status}",
    )


class IndependentVerifier:
    """Discharges typed criteria. Cannot write, credit, or commit."""

    def verify(self, criteria: list[Any], ctx: EvidenceContext) -> VerificationResult:
        """Note the signature: `criteria` and `ctx`. No transcript, by design."""
        verdicts: list[CriterionVerdict] = []
        any_discharged = False
        any_failed = False

        for c in criteria:
            kind = c.verification.kind
            if kind == "manual":
                verdicts.append(
                    CriterionVerdict(
                        statement=c.statement,
                        verification_kind="manual",
                        discharged=False,
                        evidence=None,
                    )
                )
                continue

            if kind == "command_check":
                r = _run_command(c.verification.check_id, c.verification.target, ctx)
            elif kind == "file_state":
                r = _file_state(c.verification, ctx)
            elif kind == "db_readback":
                r = _db_readback(c.verification, ctx)
            elif kind == "http_readback":
                r = _http_readback(c.verification, ctx)
            else:  # pragma: no cover - the contract's Literal forecloses it
                r = PredicateResult(False, f"unknown kind {kind!r}", uncertain=True)

            if r.satisfied:
                any_discharged = True
            else:
                any_failed = True
            verdicts.append(
                CriterionVerdict(
                    statement=c.statement,
                    verification_kind=kind,
                    discharged=r.satisfied,
                    evidence=r.evidence if r.satisfied else None,
                )
            )

        # A pass requires at least one predicate to have actually run and
        # returned true, AND nothing to have failed. `VerificationResult` rejects
        # the first violation on its own, so this is belt and braces on the rule
        # that matters most.
        passed = any_discharged and not any_failed
        return VerificationResult(
            passed=passed,
            verdicts=verdicts,
            consulted_transcript=False,  # structurally true: there is no transcript here
            notes=(
                f"{sum(1 for v in verdicts if v.discharged)} of {len(verdicts)} criteria "
                f"discharged; {sum(1 for v in verdicts if v.verification_kind == 'manual')} "
                "left undischarged for a human"
            ),
        )
