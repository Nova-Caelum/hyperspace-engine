"""Tests for the plugin's SessionStart hook (hyperspace-engine v0.1.1 part A).

The hook (`hooks/session-start.sh`, wired by `hooks/hooks.json`) primes the
`acing-hyperspace` skill on every session start — cold, resumed, cleared or
compacted — prints one status line per active loop run (bumping the
`fresh_sessions`/`compactions` budget counters on `startup`/`compact`), and
surfaces up to 5 recent local-worklog rows when the project's task graph
exists. Without this hook a compaction or `/clear` silently drops the loop,
because nothing re-primes `acing-hyperspace` (v0.1.1 brief, hook-and-tripwires).

Every subprocess environment below is built explicitly (HOME/PATH/
CLAUDE_PROJECT_DIR/CLAUDE_PLUGIN_ROOT) — never inherited — so a real
`.hyperspace/` elsewhere on the machine, or this repo's own dev `.venv`, can
never leak into what the hook sees.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import loop_state  # noqa: E402

HOOK_PATH = REPO_ROOT / "hooks" / "session-start.sh"
HOOKS_JSON_PATH = REPO_ROOT / "hooks" / "hooks.json"
PRIMER_SRC = REPO_ROOT / "skills" / "acing-hyperspace" / "SKILL.md"
SCHEMA_SQL = (REPO_ROOT / "hyperspace" / "store" / "schema.sql").read_text(encoding="utf-8")

MARKER_BEGIN = "<!-- acing-hyperspace:begin -->"
MARKER_END = "<!-- acing-hyperspace:end -->"

# Resolved once, from THIS process's own PATH — used to invoke the hook
# itself. The subprocess's own PATH (built per-test below) is what the hook
# script's internal `command -v python3` sees; it is deliberately narrower
# than this process's PATH so the "no python3 anywhere" branch can be
# exercised without also losing the ability to launch `sh` at all.
SH_PATH = shutil.which("sh") or "/bin/sh"

#: Claude Code's own hook-output cap, verified via `ctx7` against the current
#: hooks reference (2026-09-27): "Hook output strings, including
#: additionalContext, systemMessage, and plain stdout, are capped at 10,000
#: characters. Output that exceeds this limit is saved to a file and replaced
#: with a preview and file path." This is a character cap on the hook's own
#: stdout string, not a byte measurement of a larger multi-hook preload (that
#: was the vault's own canonical hook's situation, a different product).
HOOK_OUTPUT_CHAR_CAP = 10_000

SESSION_EVENTS = ("startup", "resume", "clear", "compact")

_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n\n?", re.S)


def _expected_primer_body() -> str:
    """The primer body a correct hook must deliver: the shipped SKILL.md
    with its YAML frontmatter (and the single blank line after it, if any)
    removed — computed independently of the hook's own awk implementation,
    so the two must agree rather than one merely mirroring the other."""
    text = PRIMER_SRC.read_text(encoding="utf-8")
    return _FRONTMATTER_RE.sub("", text, count=1)


def _extract_delivered_block(stdout: str) -> tuple[str | None, int, int]:
    begin_count = stdout.count(MARKER_BEGIN)
    end_count = stdout.count(MARKER_END)
    if begin_count != 1 or end_count != 1:
        return None, begin_count, end_count
    start = stdout.index(MARKER_BEGIN) + len(MARKER_BEGIN)
    end = stdout.index(MARKER_END)
    if end < start:
        return None, begin_count, end_count
    block = stdout[start:end]
    if block.startswith("\n"):
        block = block[1:]
    return block, begin_count, end_count


def _fake_bin_with_python3(tmp: Path) -> Path:
    """A directory containing a `python3` executable that is `sys.executable`
    under a guaranteed name, so the hook's `command -v python3` fallback
    branch is exercised deterministically regardless of how this test run's
    own interpreter happens to be named."""
    fake_bin = tmp / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    target = fake_bin / "python3"
    if not target.exists():
        os.symlink(sys.executable, target)
    return fake_bin


def _minimal_bin_without_python(tmp: Path) -> Path:
    """A directory carrying only the POSIX utilities `session-start.sh`
    itself calls (`awk`, `sed`, `cat`, `tr`) — deliberately excluding
    `python3`/`python`. macOS ships `/usr/bin/python3` as a stub, so simply
    narrowing `PATH` to `/usr/bin:/bin` would not actually simulate a
    python-less machine; this builds an explicit allowlist instead."""
    minimal_bin = tmp / "minimal-bin"
    minimal_bin.mkdir(exist_ok=True)
    for tool in ("awk", "sed", "cat", "tr"):
        found = shutil.which(tool)
        if found:
            link = minimal_bin / tool
            if not link.exists():
                os.symlink(found, link)
    return minimal_bin


class HookHarness(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.project_dir = self.tmp_path / "project"
        self.project_dir.mkdir()
        self.home = self.tmp_path / "home"
        self.home.mkdir()
        self.fake_bin = _fake_bin_with_python3(self.tmp_path)
        self.minimal_bin = _minimal_bin_without_python(self.tmp_path)

    def run_hook(
        self,
        *,
        source: str,
        session_id: str = "t",
        use_project_env: bool = False,
        no_python: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if use_project_env:
            env_python = self.project_dir / ".hyperspace" / "env" / "bin" / "python"
            env_python.parent.mkdir(parents=True, exist_ok=True)
            if not env_python.exists():
                os.symlink(sys.executable, env_python)
            path_value = str(self.minimal_bin)
        elif no_python:
            path_value = str(self.minimal_bin)
        else:
            path_value = f"{self.fake_bin}:{self.minimal_bin}"

        env = {
            "HOME": str(self.home),
            "PATH": path_value,
            "CLAUDE_PROJECT_DIR": str(self.project_dir),
            "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
        }
        payload = json.dumps({"source": source, "session_id": session_id})
        return subprocess.run(
            [SH_PATH, str(HOOK_PATH)],
            input=payload,
            env=env,
            cwd=str(self.project_dir),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    # -- fixture builders -------------------------------------------------

    def init_run(self, goal_slug: str = "demo-goal") -> Path:
        runs_dir = self.project_dir / "hyperspace" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        input_path = self.tmp_path / f"{goal_slug}-input.md"
        input_path.write_text("Build the thing.\n", encoding="utf-8")
        state = loop_state.LoopState.init(
            goal_slug=goal_slug,
            workspace=runs_dir,
            original_input=input_path.read_text(encoding="utf-8"),
            framework_version="test-0",
        )
        return state.path

    def make_graph_db(self, rows: list[tuple[str, str, str]]) -> Path:
        """`rows` is a list of `(created_at, author, summary)`, oldest first
        or in any order — the hook orders by `created_at DESC` itself."""
        hyperspace_dir = self.project_dir / ".hyperspace"
        hyperspace_dir.mkdir(parents=True, exist_ok=True)
        db_path = hyperspace_dir / "graph.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(SCHEMA_SQL)
            for i, (created_at, author, summary) in enumerate(rows):
                conn.execute(
                    "INSERT INTO worklog (id, author, project, summary, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (f"row-{i}", author, "demo-project", summary, created_at),
                )
            conn.commit()
        finally:
            conn.close()
        return db_path

    def write_config(self, text: str) -> Path:
        hyperspace_dir = self.project_dir / ".hyperspace"
        hyperspace_dir.mkdir(parents=True, exist_ok=True)
        config_path = hyperspace_dir / "config.toml"
        config_path.write_text(text, encoding="utf-8")
        return config_path


# (a) ----------------------------------------------------------------------


class PrimerDeliveryTests(HookHarness):
    def test_delivers_frontmatter_stripped_body_on_all_four_session_events(self) -> None:
        expected = _expected_primer_body()
        for source in SESSION_EVENTS:
            with self.subTest(source=source):
                result = self.run_hook(source=source)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
                self.assertEqual(1, begin_count, f"marker_begin count={begin_count}")
                self.assertEqual(1, end_count, f"marker_end count={end_count}")
                self.assertIsNotNone(delivered)
                self.assertEqual(expected, delivered)
                self.assertNotIn("name: acing-hyperspace", delivered)
                self.assertNotIn("derives_from:", delivered)

    def test_primer_absent_is_loud_not_silent_and_still_exits_0(self) -> None:
        """Defensive parity with the canonical primer's own tested behavior
        (not itself one of the brief's numbered RED assertions, but the same
        failure-visibility shape: a missing shipped file must not be a silent
        empty block)."""
        # CLAUDE_PLUGIN_ROOT points at an empty tree so the primer file is
        # genuinely absent, without touching the real checkout.
        empty_root = self.tmp_path / "empty-plugin-root"
        (empty_root / "skills" / "acing-hyperspace").mkdir(parents=True)
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.fake_bin}:{self.minimal_bin}",
            "CLAUDE_PROJECT_DIR": str(self.project_dir),
            "CLAUDE_PLUGIN_ROOT": str(empty_root),
        }
        result = subprocess.run(
            [SH_PATH, str(HOOK_PATH)],
            input=json.dumps({"source": "startup", "session_id": "t"}),
            env=env,
            cwd=str(self.project_dir),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
        self.assertEqual(1, begin_count)
        self.assertEqual(1, end_count)
        self.assertIn("MISSING", delivered)


# (b), (c), (d) --------------------------------------------------------------


class ActiveRunAndBudgetTests(HookHarness):
    def test_active_run_yields_one_enums_and_counts_status_line(self) -> None:
        state_path = self.init_run("demo-goal")
        state = loop_state.LoopState.load(state_path)
        state.data["gates"] = [
            {"node": "understanding", "passed": True, "passed_at": "2026-09-27T00:00:00Z"}
        ]
        state.save()

        result = self.run_hook(source="resume")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("goal=demo-goal", result.stdout)
        self.assertIn("status=framing", result.stdout)
        self.assertIn("node=framing", result.stdout)
        self.assertIn("gates_passed=1", result.stdout)
        # Never the free-text original_input field.
        self.assertNotIn("Build the thing", result.stdout)

    def test_terminal_run_yields_no_status_line(self) -> None:
        state_path = self.init_run("finished-goal")
        state = loop_state.LoopState.load(state_path)
        state.data["status"] = "done"
        state.data["final_route"] = "done"
        state.save()

        result = self.run_hook(source="startup")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("goal=finished-goal", result.stdout)

    def test_startup_and_compact_bump_exactly_once_resume_and_clear_do_not(self) -> None:
        state_path = self.init_run("budget-goal")

        result = self.run_hook(source="resume")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        data = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(0, data["budget"]["fresh_sessions"]["used"])
        self.assertEqual(0, data["budget"]["compactions"]["used"])

        result = self.run_hook(source="clear")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        data = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(0, data["budget"]["fresh_sessions"]["used"])
        self.assertEqual(0, data["budget"]["compactions"]["used"])

        result = self.run_hook(source="startup")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        data = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(1, data["budget"]["fresh_sessions"]["used"])
        self.assertEqual(0, data["budget"]["compactions"]["used"])

        result = self.run_hook(source="compact")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        data = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(1, data["budget"]["fresh_sessions"]["used"])
        self.assertEqual(1, data["budget"]["compactions"]["used"])

    def test_notify_line_appears_once_soft_cap_crossed(self) -> None:
        self.init_run("cap-goal")

        result = self.run_hook(source="startup")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("soft cap crossed", result.stdout)

        result = self.run_hook(source="startup")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("fresh_sessions: 2>1", result.stdout)
        self.assertIn("soft cap crossed", result.stdout)

    def test_bump_and_notify_also_work_via_project_hyperspace_env_python(self) -> None:
        state_path = self.init_run("env-goal")
        result = self.run_hook(source="startup", use_project_env=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        data = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(1, data["budget"]["fresh_sessions"]["used"])
        self.assertIn("goal=env-goal", result.stdout)


# (e), (f) --------------------------------------------------------------


class WorklogTests(HookHarness):
    def test_recent_worklog_rows_appear_capped_at_five_summary_author_date_only(self) -> None:
        rows = [
            (f"2026-09-{10 + i:02d}T00:00:00Z", f"author-{i}", f"summary-marker-{i}")
            for i in range(7)
        ]
        self.make_graph_db(rows)

        result = self.run_hook(source="startup")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        # Newest 5 (indices 6..2) present.
        for i in range(6, 1, -1):
            self.assertIn(f"summary-marker-{i}", result.stdout)
            self.assertIn(f"author-{i}", result.stdout)
        # Oldest 2 (indices 0, 1) absent — the cap is real, not cosmetic.
        self.assertNotIn("summary-marker-0", result.stdout)
        self.assertNotIn("summary-marker-1", result.stdout)
        # Field-selective: project/tags/client/surface/work_item_id never leak.
        self.assertNotIn("demo-project", result.stdout)

    def test_no_worklog_block_when_graph_db_absent(self) -> None:
        (self.project_dir / ".hyperspace").mkdir(parents=True)
        result = self.run_hook(source="startup")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("## Recent worklog", result.stdout)

    def test_worklog_block_omitted_when_config_declares_other_owner(self) -> None:
        self.make_graph_db([("2026-09-27T00:00:00Z", "someone", "should-not-appear")])
        self.write_config('worklog_owner = "some-other-tool"\n')

        result = self.run_hook(source="startup")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("should-not-appear", result.stdout)
        self.assertNotIn("## Recent worklog", result.stdout)

    def test_worklog_block_shown_when_config_declares_this_owner_explicitly(self) -> None:
        self.make_graph_db([("2026-09-27T00:00:00Z", "someone", "should-appear")])
        self.write_config('judge = "none"\nworklog_owner = "hyperspace-engine"\n')

        result = self.run_hook(source="startup")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("should-appear", result.stdout)


# (g) ----------------------------------------------------------------------


class NoHyperspaceSetupPointerTests(HookHarness):
    def test_no_hyperspace_dir_still_prints_primer_plus_setup_pointer(self) -> None:
        result = self.run_hook(source="startup")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
        self.assertEqual(1, begin_count)
        self.assertEqual(1, end_count)
        self.assertIsNotNone(delivered)
        self.assertIn("hyperspace-setup", result.stdout)


# (h) ----------------------------------------------------------------------


class FailOpenTests(HookHarness):
    def test_exits_0_on_corrupt_state_file(self) -> None:
        runs_dir = self.project_dir / "hyperspace" / "runs" / "broken"
        runs_dir.mkdir(parents=True)
        (runs_dir / "loop.state.json").write_text("{not json", encoding="utf-8")

        result = self.run_hook(source="startup")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
        self.assertEqual(1, begin_count)
        self.assertEqual(1, end_count)
        self.assertIsNotNone(delivered)

    def test_exits_0_on_empty_stdin(self) -> None:
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.fake_bin}:{self.minimal_bin}",
            "CLAUDE_PROJECT_DIR": str(self.project_dir),
            "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
        }
        result = subprocess.run(
            [SH_PATH, str(HOOK_PATH)],
            input="",
            env=env,
            cwd=str(self.project_dir),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
        self.assertEqual(1, begin_count)
        self.assertEqual(1, end_count)

    def test_exits_0_and_names_one_visible_line_when_no_python_available(self) -> None:
        self.init_run("no-python-goal")
        result = self.run_hook(source="startup", no_python=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
        self.assertEqual(1, begin_count)
        self.assertEqual(1, end_count)
        self.assertIn("python3", result.stdout)


# (i) ----------------------------------------------------------------------


class SizeBudgetTests(HookHarness):
    def test_total_output_under_hook_output_char_cap_on_every_source(self) -> None:
        # Worst-realistic-case fixture: an active run with a passed gate, plus
        # a full 5-row worklog — both blocks present simultaneously.
        self.init_run("size-goal")
        rows = [
            (f"2026-09-{10 + i:02d}T00:00:00Z", f"author-{i}", "x" * 180) for i in range(5)
        ]
        self.make_graph_db(rows)

        sizes: dict[str, int] = {}
        for source in SESSION_EVENTS:
            with self.subTest(source=source):
                result = self.run_hook(source=source)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                sizes[source] = len(result.stdout)
                self.assertLessEqual(
                    sizes[source],
                    HOOK_OUTPUT_CHAR_CAP,
                    f"source={source} produced {sizes[source]} chars > "
                    f"{HOOK_OUTPUT_CHAR_CAP} char hook-output cap",
                )
        print(f"session-start.sh output sizes (chars): {sizes}", file=sys.stderr)


# hooks.json shape -----------------------------------------------------------


class HooksManifestTests(unittest.TestCase):
    def test_hooks_json_wires_session_start_to_the_hook_script(self) -> None:
        data = json.loads(HOOKS_JSON_PATH.read_text(encoding="utf-8"))
        session_start_groups = data["hooks"]["SessionStart"]
        self.assertTrue(session_start_groups)
        commands = [
            hook["command"]
            for group in session_start_groups
            for hook in group["hooks"]
            if hook.get("type") == "command"
        ]
        self.assertTrue(
            any("session-start.sh" in c and "CLAUDE_PLUGIN_ROOT" in c for c in commands)
        )

    def test_hook_script_is_executable(self) -> None:
        mode = HOOK_PATH.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR, "hooks/session-start.sh must be chmod +x")


if __name__ == "__main__":
    unittest.main()
