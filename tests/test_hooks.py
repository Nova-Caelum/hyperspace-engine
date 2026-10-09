"""Tests for the plugin's SessionStart hook (hyperspace-engine v0.1.1 part A;
cross-platform since v0.1.3).

The hook (`hooks/session-start.sh` + `hooks/session_start.py`, wired by
`hooks/hooks.json`) primes the `acing-hyperspace` skill on every session
start — cold, resumed, cleared or compacted — prints the project's setup
state, one status line per active loop run (bumping the `fresh_sessions` /
`compactions` budget counters on `startup` / `compact`), and up to 5 recent
local-worklog rows when the project's task graph exists. Without this hook a
compaction or `/clear` silently drops the loop, because nothing re-primes
`acing-hyperspace` (v0.1.1 brief, hook-and-tripwires).

Every run here executes the hooks.json command string exactly as Claude Code
does: `${CLAUDE_PLUGIN_ROOT}` substituted with forward slashes, handed to
`sh -c` on macOS/Linux and to Git Bash on Windows (WINDOWS_FACTS F3, F7).
Every subprocess environment is built explicitly — never inherited — so a real
`.hyperspace/` elsewhere on the machine, or this repo's own dev `.venv`, can
never leak into what the hook sees. Output is decoded as strict UTF-8: a hook
that wrote the Windows ANSI code page would fail every test here.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sqlite3
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

from hyperspace.venv_paths import link_bin_to_scripts, native_python  # noqa: E402

HOOK_PATH = REPO_ROOT / "hooks" / "session-start.sh"
HOOK_PY_PATH = REPO_ROOT / "hooks" / "session_start.py"
HOOKS_JSON_PATH = REPO_ROOT / "hooks" / "hooks.json"
PRIMER_SRC = REPO_ROOT / "skills" / "acing-hyperspace" / "SKILL.md"
SCHEMA_SQL = (REPO_ROOT / "hyperspace" / "store" / "schema.sql").read_text(encoding="utf-8")

MARKER_BEGIN = "<!-- acing-hyperspace:begin -->"
MARKER_END = "<!-- acing-hyperspace:end -->"

IS_WINDOWS = sys.platform == "win32"

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


# ── the shell Claude Code runs a shell-form hook in ─────────────────────────


def _git_bash() -> Path | None:
    """Git Bash the way Claude Code finds it on Windows:
    `CLAUDE_CODE_GIT_BASH_PATH`, else `<Git>/bin/bash.exe` derived from
    `git.exe` on PATH (never `System32\\bash.exe`, which is WSL)."""
    override = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if override and Path(override).is_file():
        return Path(override)
    git = shutil.which("git")
    if git is None:
        return None
    for ancestor in Path(git).resolve().parents:
        candidate = ancestor / "bin" / "bash.exe"
        if candidate.is_file() and (ancestor / "usr" / "bin").is_dir():
            return candidate
    return None


def _hook_shell() -> list[str]:
    if IS_WINDOWS:
        bash = _git_bash()
        if bash is None:
            raise unittest.SkipTest(
                "Git for Windows not found — Claude Code runs shell-form plugin hooks through "
                "Git Bash on Windows, so the hook cannot run without it (WINDOWS_FACTS F7)"
            )
        return [str(bash), "-c"]
    return [shutil.which("sh") or "/bin/sh", "-c"]


def _hook_command(plugin_root: Path) -> str:
    """The hooks.json command with `${CLAUDE_PLUGIN_ROOT}` substituted — forward
    slashes on every OS, as Claude Code substitutes it (WINDOWS_FACTS F3)."""
    data = json.loads(HOOKS_JSON_PATH.read_text(encoding="utf-8"))
    command = data["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    return command.replace("${CLAUDE_PLUGIN_ROOT}", plugin_root.as_posix())


# ── fixture builders (portable) ───────────────────────────────────────────


def _write_shim(path: Path, body: str) -> Path:
    """An executable `#!/bin/sh` script — runnable by POSIX sh and by Git
    Bash alike (MSYS executes a shebang file regardless of extension)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return path


def _python_shim(path: Path, marker: Path | None = None) -> Path:
    """A shim that runs THIS test process's interpreter — and, when `marker`
    is given, records that it was the one invoked."""
    record = f'echo used >> "{marker.as_posix()}"\n' if marker is not None else ""
    return _write_shim(path, f'{record}exec "{Path(sys.executable).as_posix()}" "$@"\n')


def _planted_interpreter(env_dir: Path, marker: Path) -> None:
    """What a downloaded folder can ship at `.hyperspace/env`: an interpreter in
    either venv layout that records it was started and exits 0 — the exit status
    a probe for "is this Python 3.11+?" accepts. Nothing in a session may start it."""
    body = f'echo "started: $0 $*" >> "{marker.as_posix()}"\nexit 0\n'
    _write_shim(env_dir / "bin" / "python", body)
    _write_shim(env_dir / "Scripts" / "python.exe", body)


def _store_placeholder(path: Path) -> Path:
    """What `python3` on a fresh Windows PATH often is: the Microsoft Store
    App Execution Alias — prints an install prompt, exits 9009, runs nothing."""
    return _write_shim(
        path,
        'echo "Python was not found; run without arguments to install from the Microsoft Store" >&2\n'
        "exit 9009\n",
    )


def _tools_dirs(tmp: Path) -> list[Path]:
    """Directories carrying the utilities the hook itself calls (`sh`, `awk`,
    `sed`, `cat`, `tr`) and deliberately NO Python. POSIX: an allowlist of
    symlinks (macOS ships `/usr/bin/python3` as a stub, so narrowing PATH to
    `/usr/bin` would not simulate a python-less machine). Windows: Git's own
    `usr/bin`, which ships those tools and no Python."""
    if IS_WINDOWS:
        bash = _git_bash()
        return [bash.parent.parent / "usr" / "bin"] if bash else []
    minimal_bin = tmp / "minimal-bin"
    minimal_bin.mkdir(exist_ok=True)
    for tool in ("sh", "awk", "sed", "cat", "tr"):
        found = shutil.which(tool)
        link = minimal_bin / tool
        if found and not link.exists():
            os.symlink(found, link)
    return [minimal_bin]


def _plugin_copy(dest: Path, *, with_primer: bool = True) -> Path:
    """A plugin root elsewhere (e.g. a path with a space) carrying what the
    hook reads: `hooks/`, `bin/`, and optionally the primer."""
    shutil.copytree(REPO_ROOT / "hooks", dest / "hooks")
    shutil.copytree(REPO_ROOT / "bin", dest / "bin", ignore=shutil.ignore_patterns("__pycache__"))
    primer_dir = dest / "skills" / "acing-hyperspace"
    primer_dir.mkdir(parents=True)
    if with_primer:
        shutil.copy2(PRIMER_SRC, primer_dir / "SKILL.md")
    return dest


def _real_env(env_dir: Path, *, link: bool = True) -> Path:
    """A genuine venv (stdlib-only), in this OS's own layout — `Scripts/python.exe`
    on Windows — optionally with the `env/bin` link provisioning creates."""
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(env_dir)], check=True,
                   capture_output=True)
    if link:
        ok, message = link_bin_to_scripts(env_dir)
        assert ok, message
    return native_python(env_dir)


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


class HookHarness(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        # A space in the project path, always: every path the hook builds
        # must survive it (the Windows default profile path often has one).
        self.project_dir = self.tmp_path / "my project"
        self.project_dir.mkdir()
        self.home = self.tmp_path / "home"
        self.home.mkdir()
        self.tools = _tools_dirs(self.tmp_path)
        self.python_dir = self.tmp_path / "python-bin"
        _python_shim(self.python_dir / "python3")

    def run_hook(
        self,
        *,
        source: str | None = "startup",
        session_id: str = "t",
        path_dirs: list[Path] | None = None,
        plugin_root: Path = REPO_ROOT,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Runs the hooks.json command as Claude Code would. `path_dirs`
        (default: a working `python3`) is prepended to the tool dirs; pass
        `[]` for a machine with no Python on PATH."""
        dirs = [self.python_dir] if path_dirs is None else path_dirs
        env = {
            "HOME": str(self.home),
            "PATH": os.pathsep.join(str(d) for d in [*dirs, *self.tools]),
            # Native separators, as Claude Code exports them; the command
            # string itself carries the forward-slash substitution.
            "CLAUDE_PROJECT_DIR": str(self.project_dir),
            "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        }
        if IS_WINDOWS:
            for key in ("SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT"):
                if key in os.environ:
                    env[key] = os.environ[key]
        if stdin is None:
            stdin = json.dumps({"source": source, "session_id": session_id})
        return subprocess.run(
            [*_hook_shell(), _hook_command(plugin_root)],
            input=stdin,
            env=env,
            cwd=str(self.project_dir),
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )

    def assertRan(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    # -- project fixtures -------------------------------------------------

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

    def fresh_sessions_used(self, state_path: Path) -> int:
        return json.loads(state_path.read_text(encoding="utf-8"))["budget"]["fresh_sessions"]["used"]


# (a) ----------------------------------------------------------------------


class PrimerDeliveryTests(HookHarness):
    def test_delivers_frontmatter_stripped_body_on_all_four_session_events(self) -> None:
        expected = _expected_primer_body()
        for source in SESSION_EVENTS:
            with self.subTest(source=source):
                result = self.run_hook(source=source)
                self.assertRan(result)
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
        plugin_root = _plugin_copy(self.tmp_path / "plugin without primer", with_primer=False)
        result = self.run_hook(plugin_root=plugin_root)
        self.assertRan(result)
        delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
        self.assertEqual(1, begin_count)
        self.assertEqual(1, end_count)
        self.assertIn("MISSING", delivered)

    def test_plugin_root_with_a_space_delivers_primer_and_runs_the_python_half(self) -> None:
        plugin_root = _plugin_copy(self.tmp_path / "plugin root with space")
        state_path = self.init_run("space-goal")
        result = self.run_hook(plugin_root=plugin_root)
        self.assertRan(result)
        delivered, _, _ = _extract_delivered_block(result.stdout)
        self.assertEqual(_expected_primer_body(), delivered)
        self.assertIn("goal=space-goal", result.stdout)
        self.assertEqual(1, self.fresh_sessions_used(state_path))


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
        self.assertRan(result)
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
        self.assertRan(result)
        self.assertNotIn("goal=finished-goal", result.stdout)

    def test_startup_and_compact_bump_exactly_once_resume_and_clear_do_not(self) -> None:
        state_path = self.init_run("budget-goal")

        def used() -> tuple[int, int]:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            return data["budget"]["fresh_sessions"]["used"], data["budget"]["compactions"]["used"]

        for source, expected in (("resume", (0, 0)), ("clear", (0, 0)),
                                 ("startup", (1, 0)), ("compact", (1, 1))):
            result = self.run_hook(source=source)
            self.assertRan(result)
            self.assertEqual(expected, used(), f"after source={source}")

    def test_notify_line_appears_once_soft_cap_crossed(self) -> None:
        self.init_run("cap-goal")

        result = self.run_hook(source="startup")
        self.assertRan(result)
        self.assertNotIn("soft cap crossed", result.stdout)

        result = self.run_hook(source="startup")
        self.assertRan(result)
        self.assertIn("fresh_sessions: 2>1", result.stdout)
        self.assertIn("soft cap crossed", result.stdout)


# (e), (f) --------------------------------------------------------------


class WorklogTests(HookHarness):
    def test_recent_worklog_rows_appear_capped_at_five_summary_author_date_only(self) -> None:
        rows = [
            (f"2026-09-{10 + i:02d}T00:00:00Z", f"author-{i}", f"summary-marker-{i}")
            for i in range(7)
        ]
        self.make_graph_db(rows)

        result = self.run_hook(source="startup")
        self.assertRan(result)
        # Newest 5 (indices 6..2) present.
        for i in range(6, 1, -1):
            self.assertIn(f"summary-marker-{i}", result.stdout)
            self.assertIn(f"author-{i}", result.stdout)
        # Oldest 2 (indices 0, 1) absent — the cap is real, not cosmetic.
        self.assertNotIn("summary-marker-0", result.stdout)
        self.assertNotIn("summary-marker-1", result.stdout)
        # Field-selective: project/tags/client/surface/work_item_id never leak.
        self.assertNotIn("demo-project", result.stdout)

    def test_non_ascii_worklog_summary_arrives_as_utf8(self) -> None:
        """A Windows pipe defaults to the ANSI code page; the hook's Python
        half must still write UTF-8 (strict decoding in `run_hook`)."""
        self.make_graph_db([("2026-09-27T00:00:00Z", "someone", "arrow → and em — dash ✔")])
        result = self.run_hook(source="startup")
        self.assertRan(result)
        self.assertIn("arrow → and em — dash ✔", result.stdout)

    def test_no_worklog_block_when_graph_db_absent(self) -> None:
        (self.project_dir / ".hyperspace").mkdir(parents=True)
        result = self.run_hook(source="startup")
        self.assertRan(result)
        self.assertNotIn("## Recent worklog", result.stdout)

    def test_worklog_block_omitted_when_config_declares_other_owner(self) -> None:
        self.make_graph_db([("2026-09-27T00:00:00Z", "someone", "should-not-appear")])
        self.write_config('worklog_owner = "some-other-tool"\n')

        result = self.run_hook(source="startup")
        self.assertRan(result)
        self.assertNotIn("should-not-appear", result.stdout)
        self.assertNotIn("## Recent worklog", result.stdout)

    def test_worklog_block_shown_when_config_declares_this_owner_explicitly(self) -> None:
        self.make_graph_db([("2026-09-27T00:00:00Z", "someone", "should-appear")])
        self.write_config('judge = "none"\nworklog_owner = "hyperspace-engine"\n')

        result = self.run_hook(source="startup")
        self.assertRan(result)
        self.assertIn("should-appear", result.stdout)


# (g) ----------------------------------------------------------------------


class SetupStateTests(HookHarness):
    def test_no_hyperspace_dir_still_prints_primer_plus_setup_pointer(self) -> None:
        result = self.run_hook(source="startup")
        self.assertRan(result)
        delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
        self.assertEqual(1, begin_count)
        self.assertEqual(1, end_count)
        self.assertIsNotNone(delivered)
        self.assertIn("hyperspace-setup", result.stdout)

    def test_setup_pointer_needs_no_python(self) -> None:
        result = self.run_hook(source="startup", path_dirs=[])
        self.assertRan(result)
        self.assertIn("No .hyperspace/ found", result.stdout)
        self.assertIn("hyperspace-setup", result.stdout)

    def test_hyperspace_dir_without_env_names_the_missing_interpreter(self) -> None:
        """The MCP server is `.hyperspace/env/bin/python -m hyperspace.mcp`;
        with no environment it cannot start, and nothing else would say why —
        Claude Code shows only "failed to connect". The hook says it, with no
        Python required."""
        self.make_graph_db([])
        result = self.run_hook(source="startup", path_dirs=[])
        self.assertRan(result)
        self.assertIn("MCP server cannot start", result.stdout)
        self.assertIn(".hyperspace/env/bin/python", result.stdout)
        self.assertIn("hyperspace-setup", result.stdout)

    def test_no_missing_env_line_once_the_env_exists(self) -> None:
        self.make_graph_db([])
        _python_shim(self.project_dir / ".hyperspace" / "env" / "bin" / "python")
        result = self.run_hook(source="startup")
        self.assertRan(result)
        self.assertNotIn("MCP server cannot start", result.stdout)
        self.assertNotIn("No .hyperspace/ found", result.stdout)


# (h) ----------------------------------------------------------------------


class InterpreterResolutionTests(HookHarness):
    """Which Python the hook runs, on every OS. Observable without the hook
    printing any path: with no other Python on PATH, the active-run line only
    appears if the expected interpreter ran."""

    def test_the_project_env_is_never_the_interpreter(self) -> None:
        """Security (project interpreter, finding D). A folder can ship a file at
        `.hyperspace/env/bin/python`; the hook runs on every SessionStart in every
        folder, so it must not start that file. The computer's own Python runs
        the Python half instead, and the hook still prints what it always did."""
        state_path = self.init_run("planted-goal")
        marker = self.tmp_path / "planted-interpreter-started"
        _planted_interpreter(self.project_dir / ".hyperspace" / "env", marker)
        result = self.run_hook(source="startup")
        self.assertRan(result)
        self.assertFalse(
            marker.exists(),
            "the project's own interpreter was started:\n" + (marker.read_text() if marker.exists() else ""),
        )
        self.assertIn("goal=planted-goal", result.stdout)
        self.assertEqual(1, self.fresh_sessions_used(state_path))
        delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
        self.assertEqual((1, 1), (begin_count, end_count))
        self.assertEqual(_expected_primer_body(), delivered)

    def test_without_a_system_python_the_hook_degrades_and_still_never_starts_the_project_env(self) -> None:
        self.init_run("no-system-python-goal")
        marker = self.tmp_path / "planted-interpreter-started"
        _planted_interpreter(self.project_dir / ".hyperspace" / "env", marker)
        result = self.run_hook(source="startup", path_dirs=[])
        self.assertRan(result)
        self.assertFalse(marker.exists(), "the project's own interpreter was started as a last resort")
        self.assertNotIn("goal=no-system-python-goal", result.stdout)
        self.assertIn("No Python 3.11+ found (tried python3, python, py -3, python3.13/.12/.11)", result.stdout)
        self.assertNotIn("project environment", result.stdout)
        delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
        self.assertEqual((1, 1), (begin_count, end_count))

    def test_a_real_provisioned_env_is_not_used_either(self) -> None:
        """The refusal is of the location, not of a file that looks fake: a genuine
        venv under `.hyperspace/env` is just as much the folder's, and the hook has
        no use for it (session_start.py is stdlib-only)."""
        state_path = self.init_run("real-env-goal")
        _real_env(self.project_dir / ".hyperspace" / "env")
        result = self.run_hook(source="startup", path_dirs=[])
        self.assertRan(result)
        self.assertNotIn("goal=real-env-goal", result.stdout)
        self.assertEqual(0, self.fresh_sessions_used(state_path))
        self.assertIn("No Python 3.11+ found", result.stdout)
        self.assertNotIn("MCP server cannot start", result.stdout)

    def test_windows_scripts_layout_is_not_used_either(self) -> None:
        """An env with only `Scripts/python.exe` (no `bin` link) is passed over as
        well; the MCP-server warning, which is about `env/bin/python` existing,
        is unchanged."""
        state_path = self.init_run("scripts-goal")
        marker = self.tmp_path / "scripts-interpreter-started"
        _write_shim(
            self.project_dir / ".hyperspace" / "env" / "Scripts" / "python.exe",
            f'echo started >> "{marker.as_posix()}"\nexit 0\n',
        )
        result = self.run_hook(source="startup", path_dirs=[])
        self.assertRan(result)
        self.assertFalse(marker.exists())
        self.assertNotIn("goal=scripts-goal", result.stdout)
        self.assertEqual(0, self.fresh_sessions_used(state_path))
        self.assertIn("MCP server cannot start", result.stdout)

    def test_microsoft_store_placeholder_is_skipped_not_trusted(self) -> None:
        state_path = self.init_run("stub-goal")
        stub_dir = self.tmp_path / "windowsapps"
        _store_placeholder(stub_dir / "python3")
        marker = self.tmp_path / "python-used"
        _python_shim(self.tmp_path / "later-bin" / "python", marker)
        result = self.run_hook(source="startup", path_dirs=[stub_dir, self.tmp_path / "later-bin"])
        self.assertRan(result)
        self.assertIn("goal=stub-goal", result.stdout)
        self.assertEqual(1, self.fresh_sessions_used(state_path))
        self.assertTrue(marker.is_file())
        self.assertNotIn("Microsoft Store", result.stdout + result.stderr)

    def test_py_launcher_is_used_with_its_version_flag(self) -> None:
        """python.org's installer gives Windows `py`, often without `python3`."""
        state_path = self.init_run("py-goal")
        _write_shim(
            self.tmp_path / "launcher-bin" / "py",
            '[ "$1" = "-3" ] || { echo "py: expected -3" >&2; exit 9; }\n'
            "shift\n"
            f'exec "{Path(sys.executable).as_posix()}" "$@"\n',
        )
        result = self.run_hook(source="startup", path_dirs=[self.tmp_path / "launcher-bin"])
        self.assertRan(result)
        self.assertIn("goal=py-goal", result.stdout)
        self.assertEqual(1, self.fresh_sessions_used(state_path))

    def test_a_versioned_python_on_path_is_used_when_python3_is_too_old(self) -> None:
        """macOS ships a 3.9 `python3`; uv links only `python3.12`. The hook must
        still find a 3.11+ Python and print the active-run block."""
        state_path = self.init_run("versioned-goal")
        _write_shim(self.tmp_path / "old-bin" / "python3", "exit 1\n")  # 3.9: fails the >= 3.11 probe
        _python_shim(self.tmp_path / "new-bin" / "python3.12")
        result = self.run_hook(source="startup", path_dirs=[self.tmp_path / "old-bin", self.tmp_path / "new-bin"])
        self.assertRan(result)
        self.assertIn("goal=versioned-goal", result.stdout)
        self.assertEqual(1, self.fresh_sessions_used(state_path))
        self.assertNotIn("No Python 3.11+ found", result.stdout)

    def test_a_versioned_python_in_home_local_bin_is_used_though_it_is_not_on_path(self) -> None:
        """uv's links live in ~/.local/bin, which a hook's PATH may lack. Found by
        explicit path (a user-owned folder), and still never the project's env."""
        state_path = self.init_run("home-goal")
        marker = self.tmp_path / "planted-interpreter-started"
        _planted_interpreter(self.project_dir / ".hyperspace" / "env", marker)
        _python_shim(self.home / ".local" / "bin" / "python3.12")
        result = self.run_hook(source="startup", path_dirs=[])
        self.assertRan(result)
        self.assertFalse(marker.exists(), "the project's own interpreter was started")
        self.assertIn("goal=home-goal", result.stdout)
        self.assertEqual(1, self.fresh_sessions_used(state_path))

    def test_a_versioned_python_that_is_too_old_is_skipped_too(self) -> None:
        self.init_run("old-versioned-goal")
        _write_shim(self.tmp_path / "old-bin" / "python3.11", "exit 1\n")
        _write_shim(self.home / ".local" / "bin" / "python3.13", "exit 1\n")
        result = self.run_hook(source="startup", path_dirs=[self.tmp_path / "old-bin"])
        self.assertRan(result)
        self.assertNotIn("goal=old-versioned-goal", result.stdout)
        self.assertIn("No Python 3.11+ found", result.stdout)

    def test_too_old_python_is_skipped(self) -> None:
        self.init_run("old-goal")
        _write_shim(self.tmp_path / "old-bin" / "python3", "exit 1\n")  # fails the >= 3.11 probe
        result = self.run_hook(source="startup", path_dirs=[self.tmp_path / "old-bin"])
        self.assertRan(result)
        self.assertNotIn("goal=old-goal", result.stdout)
        self.assertIn("No Python 3.11+ found", result.stdout)


# (i) ----------------------------------------------------------------------


class FailOpenTests(HookHarness):
    def test_exits_0_on_corrupt_state_file(self) -> None:
        runs_dir = self.project_dir / "hyperspace" / "runs" / "broken"
        runs_dir.mkdir(parents=True)
        (runs_dir / "loop.state.json").write_text("{not json", encoding="utf-8")

        result = self.run_hook(source="startup")
        self.assertRan(result)
        delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
        self.assertEqual(1, begin_count)
        self.assertEqual(1, end_count)
        self.assertIsNotNone(delivered)

    def test_exits_0_on_empty_stdin(self) -> None:
        result = self.run_hook(stdin="")
        self.assertRan(result)
        self.assertIn("source=unknown", result.stdout)
        delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
        self.assertEqual(1, begin_count)
        self.assertEqual(1, end_count)

    def test_exits_0_and_names_one_visible_line_when_no_python_available(self) -> None:
        self.init_run("no-python-goal")
        result = self.run_hook(source="startup", path_dirs=[])
        self.assertRan(result)
        delivered, begin_count, end_count = _extract_delivered_block(result.stdout)
        self.assertEqual(1, begin_count)
        self.assertEqual(1, end_count)
        self.assertIn("python3", result.stdout)


# (j) ----------------------------------------------------------------------


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
                self.assertRan(result)
                sizes[source] = len(result.stdout)
                self.assertLessEqual(
                    sizes[source],
                    HOOK_OUTPUT_CHAR_CAP,
                    f"source={source} produced {sizes[source]} chars > "
                    f"{HOOK_OUTPUT_CHAR_CAP} char hook-output cap",
                )
        print(f"session-start hook output sizes (chars): {sizes}", file=sys.stderr)


# (k) the Python half, called directly ---------------------------------------


def _load_session_start():
    spec = importlib.util.spec_from_file_location("hook_session_start", HOOK_PY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PythonHalfTests(HookHarness):
    def test_render_owner_yield_and_owner_keep(self) -> None:
        module = _load_session_start()
        self.make_graph_db([("2026-09-27T00:00:00Z", "someone", "row-summary")])
        self.assertIn("row-summary", module.render(self.project_dir, REPO_ROOT, "resume"))
        self.write_config('worklog_owner = "some-other-tool"\n')
        self.assertNotIn("row-summary", module.render(self.project_dir, REPO_ROOT, "resume"))

    def test_the_python_half_needs_only_the_standard_library(self) -> None:
        """The hook runs with the computer's own Python (never the project's env),
        which has none of this project's packages. `-S` drops site-packages, so
        this is that Python: if the import chain ever needs a package, `bump`
        is skipped (loop_state fails to import) and the counter stays at 0."""
        state_path = self.init_run("stdlib-goal")
        result = subprocess.run(
            [sys.executable, "-S", str(HOOK_PY_PATH), str(self.project_dir), str(REPO_ROOT), "startup"],
            capture_output=True, encoding="utf-8", timeout=60, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("goal=stdlib-goal", result.stdout)
        self.assertEqual(1, self.fresh_sessions_used(state_path))

    def test_render_accepts_backslash_and_forward_slash_paths_alike(self) -> None:
        module = _load_session_start()
        self.init_run("slash-goal")
        native = module.render(Path(str(self.project_dir)), REPO_ROOT, "resume")
        forward = module.render(Path(self.project_dir.as_posix()), Path(REPO_ROOT.as_posix()), "resume")
        self.assertIn("goal=slash-goal", native)
        self.assertEqual(native, forward)

    def test_main_never_raises_on_bad_arguments(self) -> None:
        module = _load_session_start()
        self.assertEqual(0, module.main([]))


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

    def test_hook_script_is_executable_in_the_git_index(self) -> None:
        """The mode git records (and every clone reproduces). Read from the
        index rather than the filesystem: NTFS has no POSIX execute bit, so a
        Windows checkout's `stat` cannot answer this."""
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-s", "--", "hooks/session-start.sh"],
            capture_output=True, encoding="utf-8",
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            self.skipTest("not a git checkout — the index mode is unreadable here")
        self.assertTrue(proc.stdout.startswith("100755 "), proc.stdout)


if __name__ == "__main__":
    unittest.main()
