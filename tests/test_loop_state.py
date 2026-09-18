"""Tests for the T3.1 run-state file, schema, and reader/writer (loop_state.py)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN_DIR = HERE.parent / "bin"  # repo-root/bin (see conftest.py)
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import loop_state  # noqa: E402
import loop_terminal  # noqa: E402 — IllegalEnding, for the D1 confirm-refusal tests

SCHEMA_PATH = BIN_DIR / "loop_state.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BIN_DIR / "loop_state.py"), *args],
        text=True,
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
            loop_state.confirm(state, by="daniel")

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
            loop_state.confirm(state, by="daniel")

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

        loop_state.confirm(state, by="daniel")

        self.assertEqual("done", state.data["status"])
        self.assertEqual("done", state.data["final_route"])


if __name__ == "__main__":
    unittest.main()
