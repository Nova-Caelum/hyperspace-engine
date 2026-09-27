# Vendored from the Nova Caelum graph_library primitives/completion/landing.py, 2026-09-26.
# Adapted for hyperspace-engine; see THIRD_PARTY_NOTICES.md.
"""Step 4 — the landing check: did the change actually happen?

Delta-aware predicates over the row's TYPED criteria (handoff D7). Every
`file_state` assertion is satisfied only when it holds NOW **and** the path
changed since the row was filed — a criterion that was already true before the
work started does not discharge, without anyone having to lint for it. D4's
class is eliminated rather than patched.

Roots for a relative criterion path (D6): the project root (the directory
holding `.hyperspace/`), then the git toplevel of every repo the claim's touched
paths land in. Discovered from the claim, never configured.

`predicates.py` is reused for its containment helper and command registry and
nothing else.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .delta import PathDelta, discover_repo, path_delta, read_full, unclaimed_changes
from .predicates import _COMMANDS, _git_or_mtime, _resolve_in_root

COMMAND_TIMEOUT = 300


@dataclass
class LandingVerdict:
    statement: str
    kind: str
    discharged: bool
    failed: bool
    uncertain: bool
    evidence: str
    path: str | None = None

    @property
    def manual(self) -> bool:
        return self.kind == "manual"


@dataclass
class LandingResult:
    verdicts: list[LandingVerdict]
    roots: list[Path]
    deltas: dict[str, PathDelta] = field(default_factory=dict)   # by absolute path
    unclaimed: list[str] = field(default_factory=list)

    @property
    def any_discharged(self) -> bool:
        return any(v.discharged for v in self.verdicts)

    @property
    def any_failed(self) -> bool:
        return any(v.failed for v in self.verdicts)

    @property
    def any_uncertain(self) -> bool:
        return any(v.uncertain for v in self.verdicts)

    @property
    def passed(self) -> bool:
        # Zero discharged predicates is NOT a pass (T8). Vacuous truth is the
        # most dangerous pass there is.
        return self.any_discharged and not self.any_failed

    @property
    def discharged_count(self) -> int:
        return sum(1 for v in self.verdicts if v.discharged)


def _roots(project_root: Path, touched: list[tuple[Path, str]]) -> list[Path]:
    roots: list[Path] = [project_root.resolve()]
    for p, _ in touched:
        r = discover_repo(p)
        if r is not None and r not in roots:
            roots.append(r)
    return roots


def _added_lines(diff: str) -> str:
    return "\n".join(
        l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")
    )


class _Deltas:
    """Memoised delta per absolute path — one git walk per path per run."""

    def __init__(self, filed_at: datetime, effects: dict[str, str] | None = None) -> None:
        self.filed_at = filed_at
        self.effects = effects or {}   # resolved path → the claim's typed effect
        self.by_path: dict[str, PathDelta] = {}

    def get(self, path: Path) -> PathDelta:
        key = str(path.resolve() if path.exists() else path)
        if key not in self.by_path:
            self.by_path[key] = path_delta(path, self.filed_at, claimed_effect=self.effects.get(key))
        return self.by_path[key]


def _file_state(v: Any, roots: list[Path], deltas: _Deltas) -> LandingVerdict:
    kind = "file_state"
    st = ""  # filled by caller
    if v.assertion == "glob_exists":
        matched: list[tuple[Path, PathDelta]] = []
        for root in roots:
            try:
                for m in root.glob(v.path):
                    if _resolve_in_root(str(m.relative_to(root)), root) is None:
                        continue
                    matched.append((m, deltas.get(m)))
            except (ValueError, NotImplementedError, OSError):
                continue
        changed = [m for m, d in matched if d.changed_since_filing]
        if changed:
            return LandingVerdict(st, kind, True, False, False,
                                  f"glob {v.path!r}: {len(changed)} matching path(s) changed since filing, e.g. {changed[0]}",
                                  path=str(changed[0]))
        if matched:
            return LandingVerdict(st, kind, False, True, False,
                                  f"glob {v.path!r} matches {len(matched)} path(s) but none changed since filing — already true at filing",
                                  path=str(matched[0][0]))
        return LandingVerdict(st, kind, False, True, False, f"glob {v.path!r} matched nothing in any consulted root")

    resolved: list[tuple[Path, Path]] = []
    for root in roots:
        p = _resolve_in_root(v.path, root)
        if p is not None:
            resolved.append((root, p))
    if not resolved:
        return LandingVerdict(st, kind, False, False, True,
                              f"{v.path}: escapes every consulted root", path=v.path)

    if v.assertion == "not_exists":
        present = [p for _, p in resolved if p.exists()]
        if present:
            return LandingVerdict(st, kind, False, True, False,
                                  f"{v.path} still exists at {present[0]}", path=str(present[0]))
        # Absent everywhere. Was it present at filing? Ask the delta of the
        # first root where git can answer.
        for _, p in resolved:
            d = deltas.get(p)
            if d.existed_at_filing is True or (d.changed_since_filing and not d.exists_now):
                return LandingVerdict(st, kind, True, False, False,
                                      f"{v.path} absent now and present at filing ({d.how})", path=str(p))
            if d.existed_at_filing is False:
                return LandingVerdict(st, kind, False, True, False,
                                      f"{v.path} was already absent at filing ({d.how}) — asserts nothing about this work",
                                      path=str(p))
        return LandingVerdict(st, kind, False, False, True,
                              f"{v.path} is absent, but whether it existed at filing is unknowable here",
                              path=str(resolved[0][1]))

    # Presence-style assertions: first existing resolution wins.
    for root, p in resolved:
        if not p.exists():
            continue
        d = deltas.get(p)
        if v.assertion == "exists":
            # `exists` asserts CREATION. A file that existed at filing does not
            # discharge it however much it changed afterwards (D4).
            if d.existed_at_filing is True:
                return LandingVerdict(st, kind, False, True, False,
                                      f"{v.path} exists but was already true at filing — `exists` asserts creation, not modification ({d.how})",
                                      path=str(p))
            if d.existed_at_filing is False and d.changed_since_filing:
                return LandingVerdict(st, kind, True, False, False,
                                      f"{v.path} created after filing ({d.how})", path=str(p))
            return LandingVerdict(st, kind, False, False, True,
                                  f"{v.path} exists, but whether it existed at filing is unknowable here ({d.how}) — "
                                  f"name it in the claim's touched list as `created`, or assert with modified_after",
                                  path=str(p))
        if v.assertion == "modified_after":
            if not v.expected:
                return LandingVerdict(st, kind, False, False, True,
                                      "modified_after requires `expected` (a reference timestamp)", path=str(p))
            try:
                reference = datetime.fromisoformat(v.expected)
            except ValueError:
                return LandingVerdict(st, kind, False, False, True,
                                      f"expected {v.expected!r} is not ISO 8601", path=str(p))
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=timezone.utc)
            touched = _git_or_mtime(p, root if d.repo is None else d.repo)
            if touched is None:
                return LandingVerdict(st, kind, False, False, True,
                                      f"{v.path}: could not determine a modification time", path=str(p))
            ok = touched > reference
            return LandingVerdict(st, kind, ok, not ok, False,
                                  f"{v.path}: last touched {touched.isoformat()}, reference {reference.isoformat()}",
                                  path=str(p))
        # Both remaining assertions are deterministic predicates over the
        # WHOLE file, so each takes its own uncapped read (D-E5). `d.current`
        # stays bounded by MAX_CURRENT_CHARS for the LLM evidence judge
        # downstream and is deliberately NOT used here: a predicate evaluated
        # against that truncated copy reports FAILED with confidence for
        # anything past the boundary, instead of merely being outside the
        # check's reach.
        if v.assertion == "contains":
            expected = v.expected or ""
            full_text = read_full(p)
            if expected not in full_text:
                return LandingVerdict(st, kind, False, True, False,
                                      f"{v.path} does not contain the expected text", path=str(p))
            if not d.changed_since_filing:
                return LandingVerdict(st, kind, False, True, False,
                                      f"{v.path} contains the expected text but did not change since filing — already true at filing ({d.how})",
                                      path=str(p))
            if d.existed_at_filing is not False and not d.diff:
                # Pre-existing (or unknown-age) file, no history: we know it
                # changed, not WHAT changed. Reading the text as proof would be
                # D4 on the no-git path. Uncertain, never a pass.
                return LandingVerdict(st, kind, False, False, True,
                                      f"{v.path} changed since filing but no history shows whether the expected text was "
                                      f"added by this work ({d.how}) — keep the file under git, or assert with modified_after",
                                      path=str(p))
            if d.diff and not d.diff.startswith("(") and expected not in _added_lines(d.diff):
                return LandingVerdict(st, kind, False, True, False,
                                      f"{v.path} changed since filing, but the expected text is not in the added lines — it was already present before this work",
                                      path=str(p))
            return LandingVerdict(st, kind, True, False, False,
                                  f"{v.path} contains the expected text, added since filing ({d.how})", path=str(p))
        if v.assertion == "hash_equals":
            got = hashlib.sha256(read_full(p).encode()).hexdigest()
            if got != v.expected:
                return LandingVerdict(st, kind, False, True, False,
                                      f"{v.path} sha256={got[:16]}… ≠ expected", path=str(p))
            if not d.changed_since_filing:
                return LandingVerdict(st, kind, False, True, False,
                                      f"{v.path} matches the hash but did not change since filing — already true at filing", path=str(p))
            if d.existed_at_filing is not False and not d.diff:
                return LandingVerdict(st, kind, False, False, True,
                                      f"{v.path} matches the hash and changed since filing, but no history shows the change was this work's ({d.how})",
                                      path=str(p))
            return LandingVerdict(st, kind, True, False, False,
                                  f"{v.path} sha256={got[:16]}… matches, changed since filing ({d.how})", path=str(p))
        return LandingVerdict(st, kind, False, False, True, f"unknown assertion {v.assertion!r}", path=str(p))

    return LandingVerdict(st, kind, False, True, False,
                          f"{v.path} does not exist in any consulted root", path=str(resolved[0][1]))


# ─────────────────────────────────────────────────────────────────────────────
# D-E10 — interpreter selection, at the call site, beside `cwd`
# ─────────────────────────────────────────────────────────────────────────────
# `_COMMANDS`' Python entries are frozen to `sys.executable` — the verifier's
# own interpreter, which does not have the user's project dependencies.
# `_command()` overrides `argv[0]` only when it is still that frozen default
# (never for `["make", "build"]`). Walked from the target's directory up to
# `cwd` (never beyond it): the first co-located `<dir>/.venv/bin/python(3)`
# wins; none found falls back to `sys.executable`.


def _venv_python(venv_dir: Path) -> Path | None:
    for name in ("python3", "python"):
        candidate = venv_dir / "bin" / name
        if candidate.is_file():
            return candidate
    return None


def _resolve_interpreter(cwd: Path, target: Path | None) -> str:
    """An absolute path to an interpreter that has the OWNING repo's
    dependencies — never a bare name. Falls back to `sys.executable`."""
    anchor = cwd.resolve()
    d = (target.parent if target is not None else cwd).resolve()
    while True:
        found = _venv_python(d / ".venv")
        if found is not None:
            return str(found)
        if d == anchor or d.parent == d:
            return sys.executable
        d = d.parent


def _manual(c: Any, attestations: list[Any], user_identity: str) -> LandingVerdict:
    """A `manual` criterion binds: it discharges only against a
    `ManualAttestation` whose `statement` matches exactly and whose
    `attested_by` is the configured user identity — an agent cannot attest on
    the user's behalf. Absent that, it is `uncertain`, never a silent pass."""
    match = next((a for a in attestations if a.statement == c.statement), None)
    if match is None:
        return LandingVerdict(c.statement, "manual", False, False, True,
                              f"manual — awaiting {user_identity}'s attestation")
    if match.attested_by != user_identity:
        return LandingVerdict(c.statement, "manual", False, False, True,
                              f"manual — attested by {match.attested_by!r}, not {user_identity}; "
                              "an agent cannot attest on the user's behalf")
    return LandingVerdict(c.statement, "manual", True, False, False,
                          f"manual — attested by {user_identity}: {match.verbatim!r}")


def _command(v: Any, roots: list[Path], touched: list[tuple[Path, str]], deltas: _Deltas) -> LandingVerdict:
    kind = "command_check"
    if v.check_id == "git_diff_nonempty":
        # Redefined (L7): a change to any touched path since filing — committed
        # or not. After a commit the tree is clean and finished work must still
        # read true.
        changed = [(p, deltas.get(p)) for p, _ in touched]
        changed = [(p, d) for p, d in changed if d.changed_since_filing]
        if changed:
            return LandingVerdict("", kind, True, False, False,
                                  f"{len(changed)} touched path(s) changed since filing, e.g. {changed[0][0]} ({changed[0][1].how})")
        return LandingVerdict("", kind, False, True, False,
                              "no touched path changed since filing")
    argv = _COMMANDS.get(v.check_id)
    if argv is None:
        return LandingVerdict("", kind, False, False, True,
                              f"check_id {v.check_id!r} is not in the code-owned registry")
    # Frame agreement (B9): the command runs in the repo that owns the
    # touched paths — correct, and NOT to be undone; it was the deliberate
    # fix for the verifier running where it could see nothing. `target` is a
    # DIFFERENT frame: it is authored project-relative, resolved from the
    # project root, never from `cwd`. Mixing the two frames — appending a
    # project-relative string onto a different `cwd` — doubled the repo
    # prefix (D-E6). Resolve `target` against `roots[0]` (always the
    # project root) to an absolute path before
    # it ever reaches argv; `cwd` is unaffected either way.
    cwd = next((r for r in roots[1:]), roots[0])
    argv = list(argv)  # never mutate the shared `_COMMANDS` entry
    resolved_target: Path | None = None
    if v.target:
        resolved_target = _resolve_in_root(v.target, roots[0])
        if resolved_target is None:
            return LandingVerdict("", kind, False, False, True,
                                  f"target {v.target!r} escapes the project root")
        argv.append(str(resolved_target))
    if argv and argv[0] == sys.executable:
        # D-E10: the registry's frozen default is the verifier's OWN
        # interpreter. Override it here, beside `cwd`, with the interpreter
        # that actually has the target repo's dependencies. `["make",
        # "build"]` never matches this and is untouched.
        argv[0] = _resolve_interpreter(cwd, resolved_target)
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=COMMAND_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return LandingVerdict("", kind, False, False, True, f"`{' '.join(argv)}` could not run: {exc}")
    ok = proc.returncode == 0
    return LandingVerdict("", kind, ok, not ok, False,
                          f"`{' '.join(argv)}` in {cwd} exited {proc.returncode}")


def landing_check(criteria: list[Any], *, project_root: Path, touched: list[tuple[Path, str]],
                  filed_at: datetime, manual_attestations: list[Any] | None = None,
                  user_identity: str = "user") -> LandingResult:
    """Evaluate every typed criterion against the delta since `filed_at`, plus
    any `manual` criterion against `manual_attestations` (a manual criterion
    must bind, never be silently skipped). Note the
    signature otherwise: criteria, roots, touched paths, a timestamp. No
    account of the work — there is no parameter for one."""
    attestations = manual_attestations or []
    roots = _roots(project_root, touched)
    deltas = _Deltas(filed_at, {str(p.resolve() if p.exists() else p): eff for p, eff in touched})
    for p, _ in touched:
        deltas.get(p)  # every touched path gets a delta, whether or not a criterion names it
    manual_statements = {c.statement for c in criteria if c.verification.kind == "manual"}
    verdicts: list[LandingVerdict] = [
        LandingVerdict(a.statement, "manual_attestation", False, True, False,
                       "attestation matches no manual criterion on this row — use the exact "
                       "criterion statement, or drop the attestation")
        for a in attestations if a.statement not in manual_statements
    ]
    for c in criteria:
        kind = c.verification.kind
        if kind == "manual":
            verdicts.append(_manual(c, attestations, user_identity))
            continue
        if kind == "file_state":
            v = _file_state(c.verification, roots, deltas)
        elif kind == "command_check":
            v = _command(c.verification, roots, touched, deltas)
        else:
            v = LandingVerdict("", kind, False, False, True,
                               f"{kind} has no registry in the verifier MCP; cannot evaluate here")
        v.statement = c.statement
        verdicts.append(v)
    repos = {d.repo for d in deltas.by_path.values() if d.repo is not None}
    unclaimed = unclaimed_changes(repos, filed_at, {p for p, _ in touched}) if repos else []
    return LandingResult(verdicts=verdicts, roots=roots, deltas=dict(deltas.by_path), unclaimed=unclaimed)
