"""Run-folder schema + generated drive map (`system/bin/drive_map.py`) and its
wiring into `loop_state.py` init / set-node / gate-pass."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
BIN_DIR = HERE.parent / "bin"  # repo-root/bin (see conftest.py)
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import drive_map  # noqa: E402
import loop_state  # noqa: E402
import node_gates  # noqa: E402


class DriveMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.run = Path(self._tmp.name) / "a-run"
        self.run.mkdir()
        (self.run / "loop.state.json").write_text("{}")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_write_creates_skeleton_and_a_map_that_checks_clean(self) -> None:
        drive_map.write(self.run)
        for name, (_, create) in drive_map.FOLDERS.items():
            self.assertEqual((self.run / name).is_dir(), create, name)
        self.assertEqual(drive_map.check(self.run), [])
        self.assertIn("- `DRIVE_MAP.md`", (self.run / "DRIVE_MAP.md").read_text())

    def test_a_relative_run_dir_renders_the_same_map(self) -> None:
        drive_map.write(self.run)
        here = Path.cwd()
        try:
            os.chdir(self.run)
            self.assertEqual(drive_map.check("."), [])
        finally:
            os.chdir(here)

    def test_missing_map_is_reported(self) -> None:
        self.assertEqual(drive_map.check(self.run), ["DRIVE_MAP.md is missing"])

    def test_added_and_removed_files_make_the_map_stale_by_name(self) -> None:
        (self.run / "gone.md").write_text("x")
        drive_map.write(self.run)
        (self.run / "gone.md").unlink()
        (self.run / "notes" / "new.md").write_text("x")
        self.assertEqual(
            drive_map.check(self.run),
            ["on disk, not in the map: notes/new.md", "in the map, not on disk: gone.md"],
        )

    def test_descriptions_survive_regeneration(self) -> None:
        (self.run / "notes").mkdir()
        (self.run / "notes" / "a.md").write_text("x")
        drive_map.write(self.run)
        map_path = self.run / "DRIVE_MAP.md"
        map_path.write_text(map_path.read_text().replace("- `notes/a.md`", "- `notes/a.md` — why we chose A"))
        (self.run / "notes" / "b.md").write_text("x")
        drive_map.write(self.run)
        self.assertIn("- `notes/a.md` — why we chose A", map_path.read_text())
        self.assertEqual(drive_map.check(self.run), [])

    def test_strays_are_reported_and_ignored_names_are_not_walked(self) -> None:
        (self.run / "loose.md").write_text("x")
        (self.run / "m4-loop").mkdir()
        (self.run / "m4-loop" / "x.md").write_text("x")
        (self.run / "__pycache__").mkdir()
        (self.run / "__pycache__" / "x.pyc").write_text("x")
        self.assertEqual(drive_map.write(self.run), ["loose.md", "m4-loop/"])
        text = (self.run / "DRIVE_MAP.md").read_text()
        self.assertIn("## Outside the schema (2)", text)
        self.assertNotIn("__pycache__", text)

    def test_big_nested_folder_collapses_to_a_count_that_stays_fresh(self) -> None:
        archive = self.run / "notes" / "upstream"
        archive.mkdir(parents=True)
        for i in range(drive_map.COLLAPSE_OVER + 1):
            (archive / f"f{i:03}.txt").write_text("x")
        drive_map.write(self.run)
        map_path = self.run / "DRIVE_MAP.md"
        self.assertIn(f"- `notes/upstream/` — ({drive_map.COLLAPSE_OVER + 1} files, not listed)", map_path.read_text())
        self.assertNotIn("f000.txt", map_path.read_text())
        (archive / "one-more.txt").write_text("x")
        self.assertNotEqual(drive_map.check(self.run), [])
        drive_map.write(self.run)  # the old count must not be kept as if it were a description
        self.assertIn(f"({drive_map.COLLAPSE_OVER + 2} files, not listed)", map_path.read_text())
        self.assertNotIn(f"({drive_map.COLLAPSE_OVER + 1} files", map_path.read_text())



class EngineWiringTests(unittest.TestCase):
    """init, set-node and a passing gate each leave a map that matches the drive."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        ws = Path(self._tmp.name)
        ask = ws / "ask.md"
        ask.write_text("ask")
        self.assertEqual(loop_state.main(["init", "--goal", "g", "--input", str(ask), "--workspace", str(ws)]), 0)
        self.run = ws / "g"
        self.state = str(self.run / "loop.state.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _gate(self, *artifacts: str) -> int:
        passing = {"understanding": lambda **_: node_gates.GateResult(ok=True, messages=[], hold=False)}
        with mock.patch.dict(node_gates.CHECKS, passing):
            return loop_state.main(
                ["gate-pass", self.state, "--node", "understanding", "--by", "t", "--tests", "unused",
                 "--artifact", *artifacts]
            )

    def test_init_lays_down_skeleton_and_map(self) -> None:
        self.assertTrue((self.run / "handoffs").is_dir())
        self.assertEqual(drive_map.check(self.run), [])

    def test_set_node_and_gate_pass_each_refresh_the_map(self) -> None:
        (self.run / "notes" / "one.md").write_text("x")
        self.assertNotEqual(drive_map.check(self.run), [])
        self.assertEqual(loop_state.main(["set-node", self.state, "--node", "understanding"]), 0)
        self.assertEqual(drive_map.check(self.run), [])

        artifact = self.run / "01_understand" / "Problem.md"
        artifact.parent.mkdir()
        artifact.write_text("p")
        self.assertEqual(self._gate(str(artifact)), 0)
        self.assertEqual(drive_map.check(self.run), [])
        self.assertEqual(loop_state.check_frozen(loop_state.LoopState.load(self.state)), [])

    def test_the_map_itself_cannot_be_frozen(self) -> None:
        self.assertEqual(self._gate(str(self.run / "DRIVE_MAP.md")), 2)

    def test_cli_check_exit_codes(self) -> None:
        cli = [sys.executable, str(BIN_DIR / "drive_map.py")]
        self.assertEqual(subprocess.run([*cli, "check", str(self.run)], capture_output=True).returncode, 0)
        (self.run / "misc" / "x.md").write_text("x")
        self.assertEqual(subprocess.run([*cli, "check", str(self.run)], capture_output=True).returncode, 1)


if __name__ == "__main__":
    unittest.main()
