"""Tests for the T3.1 run-state file, schema, and reader/writer (loop_state.py)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN_DIR = HERE.parent / "bin"  # repo-root/bin (see conftest.py)
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import loop_state  # noqa: E402
import loop_terminal  # noqa: E402 — IllegalEnding, for the D1 confirm-refusal tests

from hyperspace.store import Store  # noqa: E402 — v0.1.1 item 2's gate-exit worklog log

SCHEMA_PATH = BIN_DIR / "loop_state.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BIN_DIR / "loop_state.py"), *args],
        encoding="utf-8", errors="replace",
        capture_output=True,
        check=False,
    )


class LoopStateLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self.input_path = Path(self._tmp.name) / "input.txt"
        self.input_path.write_text("Build the thing.\n", encoding="utf-8")

    def _init_state(self, goal_slug: str = "demo-goal") -> "loop_state.LoopState":
        return loop_state.LoopState.init(
            goal_slug=goal_slug,
            workspace=self.workspace,
            original_input=self.input_path.read_text(encoding="utf-8"),
            framework_version="test-0",
        )

    def test_init_creates_file_that_validates_and_records_current_node(self) -> None:
        state = self._init_state()
        state_path = self.workspace / "demo-goal" / "loop.state.json"
        self.assertTrue(state_path.exists())

        on_disk = json.loads(state_path.read_text(encoding="utf-8"))
        errors = loop_state.validate_against_schema(on_disk, SCHEMA)
        self.assertEqual([], errors)
        self.assertIsNotNone(on_disk["current_node"])
        self.assertEqual(state.data["current_node"], on_disk["current_node"])

    def test_set_node_rewrites_file_immediately(self) -> None:
        state = self._init_state()
        state_path = state.path
        before_mtime = state_path.stat().st_mtime_ns
        before_content = state_path.read_text(encoding="utf-8")
        time.sleep(0.01)

        state.set_node("understanding")

        after_mtime = state_path.stat().st_mtime_ns
        after_content = state_path.read_text(encoding="utf-8")
        self.assertNotEqual(before_mtime, after_mtime)
        self.assertNotEqual(before_content, after_content)
        self.assertEqual("understanding", state.data["current_node"])

        reloaded = loop_state.LoopState.load(state_path)
        self.assertEqual("understanding", reloaded.data["current_node"])

        # A second transition rewrites again — "every transition", not just the first.
        before_mtime_2 = state_path.stat().st_mtime_ns
        time.sleep(0.01)
        state.set_node("deciding")
        after_mtime_2 = state_path.stat().st_mtime_ns
        self.assertNotEqual(before_mtime_2, after_mtime_2)
        self.assertEqual("deciding", loop_state.LoopState.load(state_path).data["current_node"])

    def test_unknown_status_fails_validation(self) -> None:
        state = self._init_state()
        state.data["status"] = "not-a-real-status"
        with self.assertRaises(loop_state.LoopStateValidationError):
            state.validate()

    def test_read_round_trips(self) -> None:
        state = self._init_state()
        state.set_node("understanding")

        reloaded = loop_state.LoopState.load(state.path)

        self.assertEqual(state.data, reloaded.data)

    def test_status_follows_node(self) -> None:
        """T4.8 state-layer gap: `set_node` must move `status` with the
        node when `node` is itself a legal LoopStatus value, but a node
        outside that vocabulary (a free-form label) leaves `status` alone,
        and a run already at a LEGITIMATE_TERMINAL status is never moved
        off of it."""
        state = self._init_state()

        state.set_node("executing")
        self.assertEqual("executing", state.data["status"])

        state.set_node("some-free-string")
        self.assertEqual("executing", state.data["status"])
        self.assertEqual("some-free-string", state.data["current_node"])

        state.data["status"] = "done"
        state.save()
        state.set_node("executing")
        self.assertEqual("done", state.data["status"])
        self.assertEqual("executing", state.data["current_node"])

    def test_original_input_hash_stored_and_never_rewritten(self) -> None:
        state = self._init_state()
        expected_hash = hashlib.sha256(
            self.input_path.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()
        self.assertEqual(expected_hash, state.data["input_hash"])

        original_input_at_init = state.data["original_input"]
        input_hash_at_init = state.data["input_hash"]

        state.set_node("understanding")
        state.set_node("deciding")

        self.assertEqual(original_input_at_init, state.data["original_input"])
        self.assertEqual(input_hash_at_init, state.data["input_hash"])


class LoopStateValidatorTests(unittest.TestCase):
    """Unit tests for the hand-rolled draft-07 subset itself, independent of LoopState."""

    def test_missing_required_property_is_reported(self) -> None:
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
        errors = loop_state.validate_against_schema({}, schema)
        self.assertTrue(any("a" in e for e in errors))

    def test_wrong_type_is_reported(self) -> None:
        schema = {"type": "string"}
        errors = loop_state.validate_against_schema(5, schema)
        self.assertTrue(errors)

    def test_nullable_type_list_accepts_null_and_declared_type(self) -> None:
        schema = {"type": ["string", "null"]}
        self.assertEqual([], loop_state.validate_against_schema(None, schema))
        self.assertEqual([], loop_state.validate_against_schema("x", schema))
        self.assertTrue(loop_state.validate_against_schema(5, schema))

    def test_enum_violation_is_reported(self) -> None:
        schema = {"type": "string", "enum": ["a", "b"]}
        self.assertEqual([], loop_state.validate_against_schema("a", schema))
        self.assertTrue(loop_state.validate_against_schema("c", schema))

    def test_array_items_are_recursively_validated(self) -> None:
        schema = {"type": "array", "items": {"type": "integer"}}
        self.assertEqual([], loop_state.validate_against_schema([1, 2, 3], schema))
        self.assertTrue(loop_state.validate_against_schema([1, "two", 3], schema))

    def test_full_schema_passes_own_valid_fixture(self) -> None:
        state = loop_state.LoopState.init(
            goal_slug="schema-self-check",
            workspace=Path(tempfile.mkdtemp()),
            original_input="x",
            framework_version="test-0",
        )
        self.assertEqual([], loop_state.validate_against_schema(state.data, SCHEMA))


class LoopStateCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self.input_path = Path(self._tmp.name) / "input.txt"
        self.input_path.write_text("Build the thing.\n", encoding="utf-8")

    def test_cli_init_then_set_node_then_read(self) -> None:
        init_result = _run_cli(
            "init",
            "--goal", "demo-goal",
            "--input", str(self.input_path),
            "--workspace", str(self.workspace),
        )
        self.assertEqual(0, init_result.returncode, init_result.stdout + init_result.stderr)

        state_path = self.workspace / "demo-goal" / "loop.state.json"
        self.assertTrue(state_path.exists())

        set_node_result = _run_cli("set-node", str(state_path), "--node", "understanding")
        self.assertEqual(0, set_node_result.returncode, set_node_result.stdout + set_node_result.stderr)

        read_result = _run_cli("read", str(state_path))
        self.assertEqual(0, read_result.returncode, read_result.stdout + read_result.stderr)

        payload = json.loads(read_result.stdout)
        self.assertEqual("understanding", payload["current_node"])
        errors = loop_state.validate_against_schema(payload, SCHEMA)
        self.assertEqual([], errors)


class LoopEndingLiveDoneTests(unittest.TestCase):
    """D1 (nova-caelum-framework:loop-ending-executing-live-done, 2026-09-17).
    Criterion 1, verbatim: 'Passing the final node's exit gate moves a run
    from status executing to live without changing current_node; confirm
    then moves live to done for a human driver and refuses any other
    status; a run that has not passed that gate cannot be confirmed.'

    `loop_state.gate_pass()` is only ever invoked, in the real CLI path, by
    a caller (`_cmd_gate_pass`) that already confirmed `node_gates.run_check`
    returned `ok=True` — so calling the module-level `gate_pass()` directly
    here IS "a successful gate", matching how `test_artifact_freeze.py`
    exercises the same function."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self.input_path = Path(self._tmp.name) / "input.txt"
        self.input_path.write_text("Build the thing.\n", encoding="utf-8")
        self.artifact_path = Path(self._tmp.name) / "artifact.md"
        self.artifact_path.write_text("evidence\n", encoding="utf-8")

    def _init_state(self) -> "loop_state.LoopState":
        return loop_state.LoopState.init(
            goal_slug="demo-goal",
            workspace=self.workspace,
            original_input=self.input_path.read_text(encoding="utf-8"),
            framework_version="test-0",
        )

    def test_successful_executing_gate_confers_live_and_leaves_current_node(self) -> None:
        state = self._init_state()
        state.set_node("executing")
        self.assertEqual("executing", state.data["current_node"])

        loop_state.gate_pass(
            state, node="executing", artifact_paths=[self.artifact_path], frozen_by="test",
        )

        self.assertEqual("live", state.data["status"])
        self.assertEqual("executing", state.data["current_node"])
        reloaded = loop_state.LoopState.load(state.path)
        self.assertEqual("live", reloaded.data["status"])
        self.assertEqual("executing", reloaded.data["current_node"])

    def test_non_executing_gate_does_not_confer_live(self) -> None:
        state = self._init_state()
        state.set_node("specifying")

        loop_state.gate_pass(
            state, node="specifying", artifact_paths=[self.artifact_path], frozen_by="test",
        )

        self.assertEqual("specifying", state.data["status"])
        self.assertNotEqual("live", state.data["status"])

    def test_set_node_live_no_longer_confers_status_live(self) -> None:
        """The loophole D1 closes: before the fix, `set-node --node live`
        alone conferred `status=live` via the old node-name mirror,
        letting a run reach `live` without ever passing the executing
        gate. After the fix, `set_node("live")` moves `current_node` but
        leaves `status` exactly where it was."""
        state = self._init_state()

        state.set_node("live")

        self.assertEqual("live", state.data["current_node"])
        self.assertEqual("framing", state.data["status"])
        self.assertNotEqual("live", state.data["status"])

    def test_set_node_live_cannot_be_confirmed(self) -> None:
        """Criterion 1's third clause: a run that has not passed the gate
        cannot be confirmed. `set_node("live")` alone must not create a
        confirmable run."""
        state = self._init_state()

        state.set_node("live")

        with self.assertRaises(loop_terminal.IllegalEnding):
            loop_state.confirm(state, by="user")

    def test_set_node_on_a_live_run_does_not_downgrade_status(self) -> None:
        """A stray `set-node --node executing` in a resumed session must
        not un-live a finished run."""
        state = self._init_state()
        state.set_node("executing")
        loop_state.gate_pass(
            state, node="executing", artifact_paths=[self.artifact_path], frozen_by="test",
        )
        self.assertEqual("live", state.data["status"])

        state.set_node("executing")

        self.assertEqual("live", state.data["status"])
        self.assertEqual("executing", state.data["current_node"])

    def test_confirm_from_non_live_status_still_refuses(self) -> None:
        state = self._init_state()
        state.set_node("executing")  # status="executing" via the ordinary mirror, never "live"

        with self.assertRaises(loop_terminal.IllegalEnding):
            loop_state.confirm(state, by="user")

    def test_confirm_after_the_gate_passes_succeeds(self) -> None:
        """Companion positive case: `confirm` is unmodified by D1 (handoff
        §3 probe) — once the gate has genuinely conferred `live`, a human
        driver's `confirm` still moves it to `done`."""
        state = self._init_state()
        state.set_node("executing")
        loop_state.gate_pass(
            state, node="executing", artifact_paths=[self.artifact_path], frozen_by="test",
        )
        loop_state.record_approval(state, tier="human", human_present=True, authority="human")

        loop_state.confirm(state, by="user")

        self.assertEqual("done", state.data["status"])
        self.assertEqual("done", state.data["final_route"])



class InitDoesNotClobberTests(unittest.TestCase):
    """Ported from the canonical engine (init must refuse an occupied slug).
    Overwriting is how a descoped or killed run silently comes back to life:
    a fresh document resets `status` to `framing`, which puts the run back on
    the SessionStart banner and restarts its budget counters, with the
    original trail, gates, artifacts and recorded ending gone."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()

    def _init(self, slug: str = "occupied-goal", **kw) -> "loop_state.LoopState":
        return loop_state.LoopState.init(
            goal_slug=slug, workspace=self.workspace,
            original_input="x", framework_version="test-0", **kw,
        )

    def test_init_refuses_an_occupied_slug(self) -> None:
        first = self._init()
        with self.assertRaises(FileExistsError):
            self._init()
        # the original document is untouched by the refused call
        on_disk = json.loads(first.path.read_text(encoding="utf-8"))
        self.assertEqual(first.data["run_id"], on_disk["run_id"])

    def test_refusal_message_identifies_the_existing_run(self) -> None:
        first = self._init()
        with self.assertRaises(FileExistsError) as ctx:
            self._init()
        self.assertIn(first.data["run_id"], str(ctx.exception))
        self.assertIn("--force", str(ctx.exception))

    def test_a_descoped_run_cannot_be_silently_resurrected(self) -> None:
        first = self._init()
        loop_state.descope(first, decision_ref="workspace/x/Decision_Descope.md")
        self.assertEqual("descoped", first.data["status"])

        with self.assertRaises(FileExistsError):
            self._init()

        on_disk = json.loads(first.path.read_text(encoding="utf-8"))
        self.assertEqual("descoped", on_disk["status"])
        self.assertEqual("descoped", on_disk["final_route"])
        self.assertEqual(first.data["run_id"], on_disk["run_id"])  # not a new run
        self.assertEqual(1, len(on_disk["trail"]))  # trail preserved, not reset

    def test_force_replaces_the_state_document(self) -> None:
        first = self._init()
        second = self._init(force=True)
        self.assertNotEqual(first.data["run_id"], second.data["run_id"])
        self.assertEqual("framing", second.data["status"])

    def test_a_different_slug_is_never_blocked(self) -> None:
        self._init(slug="goal-a")
        other = self._init(slug="goal-b")
        self.assertEqual("framing", other.data["status"])

    def test_cli_init_exits_nonzero_on_an_occupied_slug(self) -> None:
        input_file = Path(self._tmp.name) / "original_input.md"
        input_file.write_text("raw ask", encoding="utf-8")
        args = ("init", "--goal", "cli-goal", "--input", str(input_file),
                "--workspace", str(self.workspace))

        first = _run_cli(*args)
        self.assertEqual(0, first.returncode, first.stderr)

        second = _run_cli(*args)
        self.assertNotEqual(0, second.returncode)
        self.assertIn("already exists", second.stderr)


class TerminalStatusMirrorTests(unittest.TestCase):
    """Ported from the canonical engine's event-verb tests: `descope` and
    `record_kill` mirror `final_route` into `status`, and `bump` is a no-op
    once the run has ended."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self.state = loop_state.LoopState.init(
            goal_slug="demo-goal", workspace=self.workspace,
            original_input="x", framework_version="test-0",
        )

    def test_descope_mirrors_final_route_into_status(self) -> None:
        """`descoped` is a LOOP_STATUS value and both downstream consumers
        (the SessionStart banner's filter and `bump`'s self-gate) read
        `.status`, not `.final_route`. Before this mirror existed a descoped
        run stayed visible and kept burning budget counters forever."""
        loop_state.descope(self.state, decision_ref="workspace/x/Decision_Descope.md")

        self.assertEqual("descoped", self.state.data["status"])
        self.assertTrue(loop_terminal.is_terminal(self.state.data["status"]))

    def test_record_kill_mirrors_final_route_into_status(self) -> None:
        loop_state.record_kill(self.state, reason="budget blew up")

        self.assertEqual("killed", self.state.data["status"])
        self.assertTrue(loop_terminal.is_terminal(self.state.data["status"]))

    def test_bump_is_a_no_op_after_descope(self) -> None:
        """Consumer-level proof of the mirror: the budget counters freeze
        the moment the run ends, which is what `bump`'s docstring already
        promised and what the missing mirror silently broke."""
        before = self.state.data["budget"]["fresh_sessions"]["used"]

        loop_state.descope(self.state, decision_ref="workspace/x/Decision_Descope.md")

        self.assertEqual(0, loop_state.bump(self.state, event="startup"))
        self.assertEqual(before, self.state.data["budget"]["fresh_sessions"]["used"])


def _valid_tests_json() -> dict:
    """A minimal `CandidateWorkItem`-shaped `tests.json` that clears
    `check_understanding`'s gate: one executable criterion, one `WHOLE-PATH:`
    criterion (the same shape as `test_port.py`'s `_candidate()`)."""
    return {
        "project": "demo",
        "external_id": "demo:goal-acceptance",
        "name": "Demo goal acceptance",
        "type": "task",
        "idempotency_key": "k1",
        "specification": {
            "problem": "The demo goal has no acceptance criteria written down anywhere yet.",
            "why_it_matters": "Without criteria the node cannot pass its gate and design cannot start.",
            "context_pointer": "01_understand/Problem.md in the run folder",
        },
        "source_references": [{"uri": "original_input.md"}],
        "effort_level": "quick",
        "module": None,
        "acceptance_criteria": [{
            "statement": "WHOLE-PATH: running the demo end to end writes out/result.txt",
            "verification": {"kind": "file_state", "path": "out/result.txt", "assertion": "exists"},
        }],
        "proposer_identity": "engineer",
        "proposer_surface": "cli",
        "uncertainty_notes": [],
    }


class GatePassWorklogLogTests(unittest.TestCase):
    """v0.1.1 item 2: `loop_state.py gate-pass` on exit 0 appends one
    worklog row — author `--by`, summary `"<slug>: <node> gate passed"`,
    tags `["gate", "<node>"]`, project from the run's store when
    resolvable — only when the package's store is importable and
    `<project>/.hyperspace/graph.db` exists (the run folder or an explicit
    `--project-dir`); otherwise silent. Never changes gate-pass's exit code
    or stdout contract."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _write_tests_json(self, path: Path) -> None:
        path.write_text(json.dumps(_valid_tests_json()), encoding="utf-8")

    def _init_and_advance(self, workspace: Path, slug: str) -> Path:
        workspace.mkdir(parents=True, exist_ok=True)
        input_file = workspace / f"{slug}-original_input.md"
        input_file.write_text("raw ask", encoding="utf-8")
        init = _run_cli(
            "init", "--goal", slug, "--input", str(input_file), "--workspace", str(workspace),
        )
        self.assertEqual(0, init.returncode, init.stderr)
        state_path = workspace / slug / "loop.state.json"
        set_node = _run_cli("set-node", str(state_path), "--node", "understanding")
        self.assertEqual(0, set_node.returncode, set_node.stderr)
        return state_path

    def test_no_store_resolvable_skips_silently(self) -> None:
        state_path = self._init_and_advance(self.root / "runs", "no-store-goal")
        tests_path = self.root / "tests.json"
        self._write_tests_json(tests_path)

        result = _run_cli(
            "gate-pass", str(state_path), "--node", "understanding",
            "--tests", str(tests_path), "--artifact", str(tests_path), "--by", "tester",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual("understanding", data["gates"][-1]["node"])

    def test_project_dir_flag_logs_one_row_with_expected_fields(self) -> None:
        project_dir = self.root / "project"
        project_dir.mkdir()
        Store.init(project_dir / ".hyperspace" / "graph.db").close()

        state_path = self._init_and_advance(self.root / "runs", "flagged-goal")
        tests_path = self.root / "tests.json"
        self._write_tests_json(tests_path)

        result = _run_cli(
            "gate-pass", str(state_path), "--node", "understanding",
            "--tests", str(tests_path), "--artifact", str(tests_path), "--by", "tester",
            "--project-dir", str(project_dir),
        )
        self.assertEqual(0, result.returncode, result.stderr)

        store = Store.open(project_dir / ".hyperspace" / "graph.db")
        try:
            entries = store.search_worklog(tags=["gate"])
            self.assertEqual(1, len(entries))
            entry = entries[0]
            self.assertEqual("tester", entry["author"])
            self.assertEqual("flagged-goal: understanding gate passed", entry["summary"])
            self.assertEqual(["gate", "understanding"], entry["tags"])
        finally:
            store.close()

    def test_resolves_project_dir_from_run_folder_without_explicit_flag(self) -> None:
        project_dir = self.root / "auto-project"
        project_dir.mkdir()
        Store.init(project_dir / ".hyperspace" / "graph.db").close()
        runs_dir = project_dir / "hyperspace" / "runs"

        state_path = self._init_and_advance(runs_dir, "auto-goal")
        tests_path = self.root / "tests.json"
        self._write_tests_json(tests_path)

        result = _run_cli(
            "gate-pass", str(state_path), "--node", "understanding",
            "--tests", str(tests_path), "--artifact", str(tests_path), "--by", "tester",
        )
        self.assertEqual(0, result.returncode, result.stderr)

        store = Store.open(project_dir / ".hyperspace" / "graph.db")
        try:
            entries = store.search_worklog(tags=["gate"])
            self.assertEqual(1, len(entries))
        finally:
            store.close()

    def test_project_resolved_only_when_exactly_one_project_row(self) -> None:
        project_dir = self.root / "project-code"
        project_dir.mkdir()
        store = Store.init(project_dir / ".hyperspace" / "graph.db")
        store.upsert_project(code="demo-project", name="Demo")
        store.close()

        state_path = self._init_and_advance(self.root / "runs2", "project-goal")
        tests_path = self.root / "tests.json"
        self._write_tests_json(tests_path)

        result = _run_cli(
            "gate-pass", str(state_path), "--node", "understanding",
            "--tests", str(tests_path), "--artifact", str(tests_path), "--by", "tester",
            "--project-dir", str(project_dir),
        )
        self.assertEqual(0, result.returncode, result.stderr)

        store = Store.open(project_dir / ".hyperspace" / "graph.db")
        try:
            entries = store.search_worklog(tags=["gate"])
            self.assertEqual(1, len(entries))
            self.assertEqual("demo-project", entries[0]["project"])
        finally:
            store.close()

    def test_store_presence_never_changes_exit_code_or_stdout_shape(self) -> None:
        """Comparative check: with and without a resolvable store, the CLI's
        exit code and JSON key set are identical — the log never touches the
        gate-pass contract (brief: 'never change gate-pass's exit code or
        stdout contract')."""
        tests_path = self.root / "tests.json"
        self._write_tests_json(tests_path)

        state_path_a = self._init_and_advance(self.root / "runs-a", "compare-a")
        without_store = _run_cli(
            "gate-pass", str(state_path_a), "--node", "understanding",
            "--tests", str(tests_path), "--artifact", str(tests_path), "--by", "tester",
        )

        project_dir = self.root / "compare-project"
        project_dir.mkdir()
        Store.init(project_dir / ".hyperspace" / "graph.db").close()
        state_path_b = self._init_and_advance(self.root / "runs-b", "compare-b")
        with_store = _run_cli(
            "gate-pass", str(state_path_b), "--node", "understanding",
            "--tests", str(tests_path), "--artifact", str(tests_path), "--by", "tester",
            "--project-dir", str(project_dir),
        )

        self.assertEqual(without_store.returncode, with_store.returncode)
        self.assertEqual(
            set(json.loads(without_store.stdout).keys()),
            set(json.loads(with_store.stdout).keys()),
        )


def _git(root: Path, *args: str, date: str | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else None
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=root, check=True, capture_output=True, encoding="utf-8", errors="replace", env=env,
    )


def _ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


class GatePassExecutingHoldTests(unittest.TestCase):
    """v0.1.1 item 3, whole-path: `check_executing`'s manual-criterion HOLD
    (exit 3) wired end-to-end through `loop_state.py gate-pass --node
    executing --project-dir` against a REAL local-verifier run (not a
    synthetic dict — `tests/test_node_gates_store.py` covers `check_executing`
    directly). An undischarged `manual` criterion on a non-live-test row
    holds naming the row; attested, the same row passes."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.project_dir = self.root / "proj"
        self.project_dir.mkdir()
        (self.project_dir / ".gitignore").write_text(".hyperspace/\n", encoding="utf-8")
        (self.project_dir / "README.md").write_text("demo\n", encoding="utf-8")
        _git(self.project_dir, "init", "-q")
        _git(self.project_dir, "add", ".")
        _git(self.project_dir, "commit", "-q", "-m", "init", date=_ago(120))

        from hyperspace.store import Store as _Store
        self.store = _Store.init(self.project_dir / ".hyperspace" / "graph.db")
        self.store.upsert_project(code="demo-project", name="Demo")

    def tearDown(self) -> None:
        self.store.close()

    def _file_row(self, ext: str) -> None:
        from hyperspace.tools import call_tool
        result = call_tool(self.store, "upsert_work_item", {
            "project": "demo-project", "external_id": ext, "name": "Produce the result file",
            "type": "task", "state": "ready", "parent_work_item": None, "assignee_agent": None,
            "team": None, "idempotency_key": f"{ext}-create",
            "specification": {
                "problem": "The project has no result file, so nothing downstream can read the outcome.",
                "why_it_matters": "Downstream steps read out/result.txt; without it they have nothing to consume.",
                "context_pointer": "tests/test_loop_state.py fixture.",
            },
            "source_references": [{"uri": "tests/test_loop_state.py"}], "effort_level": "quick", "module": None,
            "acceptance_criteria": [
                {"statement": "The result file is created by the work.",
                 "verification": {"kind": "file_state", "path": "out/result.txt", "assertion": "exists"}},
                {"statement": "The user has read the result file and confirms it is right.",
                 "verification": {"kind": "manual", "instruction": "Open out/result.txt and confirm it reads right."}},
            ],
            "proposer_identity": "engineer", "proposer_surface": "cli-mac", "uncertainty_notes": [],
        })
        self.assertNotIn("error", result, result)

    def _write_result(self) -> None:
        time.sleep(0.02)
        p = self.project_dir / "out" / "result.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("result\n", encoding="utf-8")

    def _close(self, ext: str, attestations: list[dict] | None = None) -> dict:
        from hyperspace.judge import NoneJudge
        from hyperspace.verify import CompletionClaim, ManualAttestation, complete_workitem, local_deps

        deps = local_deps(self.store, NoneJudge(), project_root=self.project_dir)
        claim = CompletionClaim(
            project="demo-project", external_id=ext,
            touched=[{"path": "out/result.txt", "effect": "created"}],
            idempotency_key=f"{ext}-done", proposer_identity="engineer", proposer_surface="cli-mac",
            manual_attestations=[ManualAttestation(**a) for a in (attestations or [])],
        )
        return asyncio.run(complete_workitem(claim, deps))

    def _run_gate(self, ext: str) -> subprocess.CompletedProcess[str]:
        workspace = self.root / "runs"
        input_file = self.root / "original_input.md"
        input_file.write_text("raw ask", encoding="utf-8")
        init = _run_cli("init", "--goal", "hold-goal", "--input", str(input_file), "--workspace", str(workspace))
        self.assertEqual(0, init.returncode, init.stderr)
        state_path = workspace / "hold-goal" / "loop.state.json"
        _run_cli("set-node", str(state_path), "--node", "executing")

        workplan = self.root / "workplan.json"
        workplan.write_text(json.dumps({"project": "demo-project", "work_items": [{"external_id": ext}]}), encoding="utf-8")
        reconciliation = self.root / "RECONCILIATION.md"
        reconciliation.write_text(f"- {ext} → done\n", encoding="utf-8")

        return _run_cli(
            "gate-pass", str(state_path), "--node", "executing",
            "--workplan", str(workplan), "--reconciliation", str(reconciliation),
            "--artifact", str(workplan), "--by", "tester", "--project-dir", str(self.project_dir),
        )

    def test_undischarged_manual_holds_naming_the_row(self) -> None:
        ext = "demo-project:hold"
        self._file_row(ext)
        self._write_result()
        out = self._close(ext)  # no attestation -> unverifiable, recorded in verifier_runs
        self.assertEqual("unverifiable", out["outcome"], out)

        result = self._run_gate(ext)

        self.assertEqual(3, result.returncode, result.stderr)
        self.assertIn(ext, result.stderr)

    def test_attested_manual_passes(self) -> None:
        ext = "demo-project:hold2"
        self._file_row(ext)
        self._write_result()
        out = self._close(ext, attestations=[{
            "statement": "The user has read the result file and confirms it is right.",
            "attested_by": "user", "verbatim": "yes, confirmed",
        }])
        self.assertEqual("done", out["outcome"], out)

        result = self._run_gate(ext)

        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
