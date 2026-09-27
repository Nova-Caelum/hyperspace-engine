# Vendored from the Nova Caelum graph_library primitives/completion/delta.py, 2026-09-26.
# Adapted for hyperspace-engine; see THIRD_PARTY_NOTICES.md.
"""Evidence is a DELTA, not a state (handoff D7) — and roots are discovered, not
listed (D6).

Every predicate in the old verifier asked "is this true NOW", which cannot
separate *the work caused this* from *it was already like that*. D4 was four
rows validated clean against files that predated the work. This module answers
the question that actually matters: **what changed at this path since the row
was filed?** — from git where git exists, from mtime where it does not, and
with `unknown` said out loud where neither can answer.

Read-only. Nothing here writes to any tree.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

GIT_TIMEOUT = 20
MAX_DIFF_CHARS = 20_000
MAX_CURRENT_CHARS = 60_000


def _git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode, proc.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def discover_repo(path: Path) -> Path | None:
    """The enclosing git toplevel of `path`, walking up to the nearest existing
    ancestor first (a `created` path that does not exist yet still has one).
    Zero configuration, never stale: a repo created next month works the day
    it is created."""
    probe = path if path.is_dir() else path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    rc, out = _git(probe, "rev-parse", "--show-toplevel")
    if rc != 0 or not out.strip():
        return None
    return Path(out.strip()).resolve()


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _commit_parent(repo: Path, commit: str) -> str | None:
    rc, out = _git(repo, "rev-parse", f"{commit}^")
    return out.strip() if rc == 0 and out.strip() else None


def _partition_filing_second(repo: Path, base: str | None, commits_since: list[str]) -> str | None:
    """Enforce the invariant: no commit may be classified as both `base`
    (at-or-before filing) and a member of `commits_since` (since filing).

    Git commit timestamps have 1-second resolution, and `--before`/`--since`
    both floor `since`'s sub-second remainder before comparing inclusively
    (empirically verified) — so a commit landing in `filed_at`'s own whole
    second, the filing_second, can satisfy BOTH boundary queries at once and
    get picked as `base` while also sitting in `commits_since`. Partition
    that second explicitly rather than trusting the two flags to agree: walk
    `base` back through parents until it is unambiguously outside
    `commits_since`. `None` only when that chain runs out — a naive
    `base = None` on first ambiguity would silently lose the content diff
    for every row whose repo HAS pre-filing history (the parent commit is
    the correct fallback, not the absence of one)."""
    since_hashes = {line.split(" ", 1)[0] for line in commits_since}
    seen: set[str] = set()
    while base is not None and base in since_hashes:
        if base in seen:  # defensive: never loop on a corrupt/cyclical graph
            return None
        seen.add(base)
        base = _commit_parent(repo, base)
    return base


def _mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


@dataclass
class PathDelta:
    path: Path
    repo: Path | None
    exists_now: bool
    existed_at_filing: bool | None      # None = unknowable from here
    changed_since_filing: bool
    how: str                            # the observation that decided `changed_since_filing`
    diff: str = ""                      # bounded change since filing, when it can be shown
    current: str = ""                   # bounded current content, when it exists and is text
    tracked: bool | None = None
    commits_since: list[str] = field(default_factory=list)


def _read_current(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_CURRENT_CHARS]
    except OSError:
        return ""


def read_full(path: Path) -> str:
    """The WHOLE current text of `path`, uncapped — for predicates that must
    decide deterministically over the entire file (`contains`'s presence
    gate). `MAX_CURRENT_CHARS` exists to protect the LLM evidence judge
    downstream (`judges/semantics_agent.py`), which consumes
    `PathDelta.current` alone and re-bounds it again itself; it has no
    bearing on what a deterministic predicate needs to read. Never fed to a
    model — callers that need the judge-facing copy use `PathDelta.current`,
    which stays capped regardless of this function (D-E5)."""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def path_delta(path: Path, filed_at: datetime, *, repo: Path | None = None,
               claimed_effect: str | None = None) -> PathDelta:
    """What changed at `path` since `filed_at`. `repo` may be passed when the
    caller already discovered it; otherwise it is discovered here.

    `claimed_effect` is the claim's typed `created|modified|deleted` for this
    path, if the claim named it. It is consulted ONLY where no history exists
    to say whether the path predates the filing (no git, or a repo whose first
    commit is after filing): the clocks can prove pre-existence (birthtime or
    mtime at or before filing) but never creation — every atomic-save writer
    (Claude Code Edit/Write, `sed -i`, most editors) gives a rewritten file a
    fresh inode and birthtime (probed 2026-09-06). A claim of `created` that
    the clocks do not contradict is accepted as created; `modified` means the
    file predates the work and its delta is unknowable; no claim → unknowable.
    """
    path = path.resolve() if path.exists() else path
    repo = repo or discover_repo(path)
    exists_now = path.exists()
    since = _iso(filed_at)

    if repo is None:
        return _mtime_delta(path, filed_at, exists_now, claimed_effect=claimed_effect)

    try:
        rel = str(path.relative_to(repo))
    except ValueError:
        return _mtime_delta(path, filed_at, exists_now, claimed_effect=claimed_effect)

    # The last commit at or before filing — the "before" the delta is measured from.
    rc, out = _git(repo, "rev-list", "-1", f"--before={since}", "HEAD")
    base = out.strip() if rc == 0 and out.strip() else None

    # Is the path tracked at HEAD?
    rc, out = _git(repo, "ls-files", "--error-unmatch", "--", rel)
    tracked = rc == 0

    # Commits touching the path since filing (committer date).
    rc, out = _git(repo, "log", f"--since={since}", "--format=%H %cI", "--", rel)
    commits_since = [l.strip() for l in out.splitlines() if l.strip()] if rc == 0 else []

    # No commit may be both `base` and a member of `commits_since` — see
    # `_partition_filing_second`'s docstring for why the two inclusive git
    # queries can otherwise agree on the same commit.
    base = _partition_filing_second(repo, base, commits_since)

    existed_at_filing: bool | None
    if base:
        rc, _ = _git(repo, "cat-file", "-e", f"{base}:{rel}")
        existed_at_filing = rc == 0
    else:
        # The repo has no commit from before filing: git cannot say whether the
        # path predates the row. The clocks can prove pre-existence; the claim
        # resolves the rest (see the docstring).
        existed_at_filing = _resolve_no_history(path, filed_at, claimed_effect)

    # Uncommitted state of the path.
    rc, out = _git(repo, "status", "--porcelain", "--untracked-files=all", "--", rel)
    status = out.strip()[:2] if rc == 0 and out.strip() else ""

    diff = ""
    if status.startswith("??"):
        mt = _mtime(path)
        if mt is not None and mt <= _aware(filed_at) and existed_at_filing is None:
            # Untracked and older than the filing: it was already there.
            return PathDelta(path, repo, exists_now, True, False,
                             f"untracked, mtime {mt.isoformat()} is not after filing",
                             current=_read_current(path), tracked=False)
        if mt is not None and mt <= _aware(filed_at):
            return PathDelta(path, repo, exists_now, existed_at_filing if existed_at_filing is not None else True,
                             False, f"untracked, mtime {mt.isoformat()} is not after filing",
                             current=_read_current(path), tracked=False)
        current = _read_current(path)
        return PathDelta(path, repo, exists_now, False if existed_at_filing is None else existed_at_filing,
                         True, "untracked file newer than the filing", diff=f"(new file)\n{current[:MAX_DIFF_CHARS]}",
                         current=current, tracked=False)

    changed = bool(commits_since) or bool(status)
    if changed:
        how_parts = []
        if commits_since:
            how_parts.append(f"{len(commits_since)} commit(s) since filing: {commits_since[0][:7]}…")
        if status:
            how_parts.append(f"uncommitted ({status.strip()})")
        how = "; ".join(how_parts)
        if base:
            rc, out = _git(repo, "diff", base, "--", rel)
            diff = out[:MAX_DIFF_CHARS] if rc == 0 else ""
        elif existed_at_filing is False:
            diff = "(new file; repo has no commit from before filing)\n" + _read_current(path)[:MAX_DIFF_CHARS]
        else:
            diff = ""  # pre-existing or unknowable, and no history shows WHAT changed
            how += "; repo has no commit from before filing, so no history shows WHAT changed"
        if not diff.strip() and exists_now and existed_at_filing is False:
            diff = "(change recorded by git but the content diff is empty — e.g. mode or rename)"
    else:
        how = "no commit and no uncommitted change at this path since filing"
        if not tracked and exists_now:
            # Exists, not tracked, not reported by status (ignored?) — fall back to mtime.
            # `claimed_effect` must survive this fallback exactly like the two
            # siblings above (no repo; path outside repo) — dropping it here
            # left `existed_at_filing` permanently `None` for every git-ignored
            # path (D-E4). a git-ignored working folder is the usual case, and many
            # filed criteria point there (see module docstring).
            return _mtime_delta(path, filed_at, exists_now, repo=repo, claimed_effect=claimed_effect)

    return PathDelta(path, repo, exists_now, existed_at_filing, changed, how,
                     diff=diff, current=_read_current(path), tracked=tracked,
                     commits_since=commits_since)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _birthtime(path: Path) -> datetime | None:
    """Creation time of the current inode (APFS `st_birthtime`). None where
    the platform lacks it. Proves pre-existence when at or before filing;
    proves nothing when after it (atomic-save writers rotate the inode)."""
    try:
        return datetime.fromtimestamp(path.stat().st_birthtime, tz=timezone.utc)
    except (OSError, AttributeError):
        return None


def _resolve_no_history(path: Path, filed_at: datetime, claimed_effect: str | None) -> bool | None:
    """`existed_at_filing` where no history exists. True when a clock proves
    the file predates filing; else the claim's typed effect decides; else
    unknowable."""
    filed = _aware(filed_at)
    bt, mt = _birthtime(path), _mtime(path)
    if (bt is not None and bt <= filed) or (mt is not None and mt <= filed):
        return True
    if claimed_effect == "created":
        return False
    if claimed_effect in ("modified", "deleted"):
        return True
    return None


def _mtime_delta(path: Path, filed_at: datetime, exists_now: bool, *, repo: Path | None = None,
                 claimed_effect: str | None = None) -> PathDelta:
    """Outside git (or git-ignored — the vault's `workspace/` is, and most
    filed criteria point there): clocks plus the claim, honestly labelled.

    * clock at or before filing            → pre-existing; unchanged if mtime
      is also at or before filing, else touched with no history of WHAT.
    * clocks after filing + claim `created` → created by this work; the whole
      content is the delta.
    * clocks after filing + claim `modified` → pre-existing, touched, no
      history of WHAT changed. `diff` stays empty so `contains` cannot read
      current content as proof (D4's class on the no-git path).
    * clocks after filing + no claim        → unknowable.
    """
    if not exists_now:
        return PathDelta(path, repo, False, None, False,
                         "does not exist and no git history to say whether it ever did")
    mt, bt = _mtime(path), _birthtime(path)
    filed = _aware(filed_at)
    if mt is None:
        return PathDelta(path, repo, True, None, False, "exists; mtime unreadable")
    current = _read_current(path)
    clocks = f"birthtime {bt.isoformat() if bt else 'unknown'}, mtime {mt.isoformat()}"
    if mt <= filed:
        return PathDelta(path, repo, True, True, False,
                         f"no git; mtime is not after filing ({clocks})", current=current, tracked=None)
    existed = _resolve_no_history(path, filed_at, claimed_effect)
    if existed is False:
        return PathDelta(path, repo, True, False, True,
                         f"no git; claimed created and no clock contradicts it ({clocks})",
                         diff="(new file)\n" + current[:MAX_DIFF_CHARS], current=current, tracked=None)
    if existed is True:
        why = "a clock predates filing" if (bt is not None and bt <= filed) else "claimed modified"
        return PathDelta(path, repo, True, True, True,
                         f"no git; pre-existing file ({why}) touched after filing; no history shows WHAT changed ({clocks})",
                         diff="", current=current, tracked=None)
    return PathDelta(path, repo, True, None, True,
                     f"no git; touched after filing, not named in the claim, so whether it predates the row is unknowable ({clocks})",
                     diff="", current=current, tracked=None)


def changed_paths_since(repo: Path, filed_at: datetime) -> set[str]:
    """Every repo-relative path changed since filing — committed or not."""
    out_paths: set[str] = set()
    rc, out = _git(repo, "log", f"--since={_iso(filed_at)}", "--format=", "--name-only")
    if rc == 0:
        out_paths |= {l.strip() for l in out.splitlines() if l.strip()}
    rc, out = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if rc == 0:
        for line in out.splitlines():
            if len(line) > 3:
                p = line[3:].strip()
                if " -> " in p:
                    p = p.split(" -> ", 1)[1]
                out_paths.add(p)
    return out_paths


def _top_level(rel: Path) -> str:
    """The first path component under a repo, or `"."` for a bare file sitting
    directly at the repo root — the root is its own shared neighbourhood, so
    two root-level siblings count as the same top-level place."""
    return rel.parts[0] if len(rel.parts) > 1 else "."


def unclaimed_changes(repos: set[Path], filed_at: datetime, claimed: set[Path]) -> list[str]:
    """Paths changed since filing in the claim's repos that the claim did not
    name, scoped to the top-level directories the claim's OWN touched paths
    fall under — the caller's neighbourhood, where an omission is meaningful.
    ADVISORY (D8): listed, never a verdict.

    Every in-scope entry is shown in full; there is no cap. Changes outside
    the touched list's top-level directories are not silently dropped either
    — they are folded into a single trailing count line, once, after every
    repo has been walked."""
    claimed_resolved = {p.resolve() if p.exists() else p for p in claimed}
    allowed_by_repo: dict[Path, set[str]] = {}
    for p in claimed_resolved:
        repo = discover_repo(p)
        if repo is None:
            continue
        try:
            rel = p.relative_to(repo)
        except ValueError:
            continue
        allowed_by_repo.setdefault(repo, set()).add(_top_level(rel))

    found: list[str] = []
    filtered_out = 0
    for repo in sorted(repos):
        allowed = allowed_by_repo.get(repo, set())
        for rel in sorted(changed_paths_since(repo, filed_at)):
            abs_path = (repo / rel)
            abs_path = abs_path.resolve() if abs_path.exists() else abs_path
            if abs_path in claimed_resolved:
                continue
            if _top_level(Path(rel)) not in allowed:
                filtered_out += 1
                continue
            found.append(str(abs_path))
    if filtered_out:
        found.append(f"… {filtered_out} further change(s) outside the touched list's directories")
    return found
