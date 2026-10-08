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
        (self.run / "loop.state.json").write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_write_creates_skeleton_and_a_map_that_checks_clean(self) -> None:
        drive_map.write(self.run)
        for name, (_, create) in drive_map.FOLDERS.items():
            self.assertEqual((self.run / name).is_dir(), create, name)
        self.assertEqual(drive_map.check(self.run), [])
        self.assertIn("- `DRIVE_MAP.md`", (self.run / "DRIVE_MAP.md").read_text(encoding="utf-8"))

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
        (self.run / "gone.md").write_text("x", encoding="utf-8")
        drive_map.write(self.run)
        (self.run / "gone.md").unlink()
        (self.run / "notes" / "new.md").write_text("x", encoding="utf-8")
        self.assertEqual(
            drive_map.check(self.run),
            ["on disk, not in the map: notes/new.md", "in the map, not on disk: gone.md"],
        )

    def test_descriptions_survive_regeneration(self) -> None:
        (self.run / "notes").mkdir()
        (self.run / "notes" / "a.md").write_text("x", encoding="utf-8")
        drive_map.write(self.run)
        map_path = self.run / "DRIVE_MAP.md"
        map_path.write_text(map_path.read_text(encoding="utf-8").replace("- `notes/a.md`", "- `notes/a.md` — why we chose A"), encoding="utf-8")
        (self.run / "notes" / "b.md").write_text("x", encoding="utf-8")
        drive_map.write(self.run)
        self.assertIn("- `notes/a.md` — why we chose A", map_path.read_text(encoding="utf-8"))
        self.assertEqual(drive_map.check(self.run), [])

    def test_strays_are_reported_and_ignored_names_are_not_walked(self) -> None:
        (self.run / "loose.md").write_text("x", encoding="utf-8")
        (self.run / "m4-loop").mkdir()
        (self.run / "m4-loop" / "x.md").write_text("x", encoding="utf-8")
        (self.run / "__pycache__").mkdir()
        (self.run / "__pycache__" / "x.pyc").write_text("x", encoding="utf-8")
        self.assertEqual(drive_map.write(self.run), ["loose.md", "m4-loop/"])
        text = (self.run / "DRIVE_MAP.md").read_text(encoding="utf-8")
        self.assertIn("## Outside the schema (2)", text)
        self.assertNotIn("__pycache__", text)

    def test_big_nested_folder_collapses_to_a_count_that_stays_fresh(self) -> None:
        archive = self.run / "notes" / "upstream"
        archive.mkdir(parents=True)
        for i in range(drive_map.COLLAPSE_OVER + 1):
            (archive / f"f{i:03}.txt").write_text("x", encoding="utf-8")
        drive_map.write(self.run)
        map_path = self.run / "DRIVE_MAP.md"
        self.assertIn(f"- `notes/upstream/` — ({drive_map.COLLAPSE_OVER + 1} files, not listed)", map_path.read_text(encoding="utf-8"))
        self.assertNotIn("f000.txt", map_path.read_text(encoding="utf-8"))
        (archive / "one-more.txt").write_text("x", encoding="utf-8")
        self.assertNotEqual(drive_map.check(self.run), [])
        drive_map.write(self.run)  # the old count must not be kept as if it were a description
        self.assertIn(f"({drive_map.COLLAPSE_OVER + 2} files, not listed)", map_path.read_text(encoding="utf-8"))
        self.assertNotIn(f"({drive_map.COLLAPSE_OVER + 1} files", map_path.read_text(encoding="utf-8"))



class EngineWiringTests(unittest.TestCase):
    """init, set-node and a passing gate each leave a map that matches the drive."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        ws = Path(self._tmp.name)
        ask = ws / "ask.md"
        ask.write_text("ask", encoding="utf-8")
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
        (self.run / "notes" / "one.md").write_text("x", encoding="utf-8")
        self.assertNotEqual(drive_map.check(self.run), [])
        self.assertEqual(loop_state.main(["set-node", self.state, "--node", "understanding"]), 0)
        self.assertEqual(drive_map.check(self.run), [])

        artifact = self.run / "01_understand" / "Problem.md"
        artifact.parent.mkdir()
        artifact.write_text("p", encoding="utf-8")
        self.assertEqual(self._gate(str(artifact)), 0)
        self.assertEqual(drive_map.check(self.run), [])
        self.assertEqual(loop_state.check_frozen(loop_state.LoopState.load(self.state)), [])

    def test_the_map_itself_cannot_be_frozen(self) -> None:
        self.assertEqual(self._gate(str(self.run / "DRIVE_MAP.md")), 2)

    def test_cli_check_exit_codes(self) -> None:
        cli = [sys.executable, str(BIN_DIR / "drive_map.py")]
        self.assertEqual(subprocess.run([*cli, "check", str(self.run)], capture_output=True).returncode, 0)
        (self.run / "misc" / "x.md").write_text("x", encoding="utf-8")
        self.assertEqual(subprocess.run([*cli, "check", str(self.run)], capture_output=True).returncode, 1)


def _tree_paths(text: str) -> list[str]:
    """Paths on the `- `path`` lines under the map's Tree heading, in order."""
    out: list[str] = []
    in_tree = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_tree = line.strip() == "## Tree"
            continue
        match = drive_map._MAP_LINE.match(line) if in_tree else None
        if match:
            out.append(match.group("path"))
    return out


class TreeModeTests(unittest.TestCase):
    """`drive_map.py tree <root> --out <file>`: a whole-project map driven by `.drivemap.toml`."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "proj"
        self.root.mkdir()
        self.out = base / "out" / "map.md"  # outside the root unless a test says otherwise

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def touch(self, *rels: str) -> None:
        for rel in rels:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")

    def config(self, text: str) -> None:
        (self.root / ".drivemap.toml").write_text(text, encoding="utf-8")

    def build(self) -> str:
        drive_map.write_tree(self.root, self.out)
        return self.out.read_text(encoding="utf-8")

    # -- config ---------------------------------------------------------------
    def test_defaults_are_depth_3_and_400_lines_without_a_toml(self) -> None:
        cfg = drive_map.load_tree_config(self.root)
        self.assertEqual((cfg.max_depth, cfg.budget, cfg.cutoff), (3, 400, ()))
        self.assertIn(".*", cfg.exclude)

    def test_the_toml_holds_exclude_cutoff_max_depth_and_budget(self) -> None:
        self.config('exclude = ["*.log"]\ncutoff = ["big"]\nmax_depth = 2\nbudget = 50\n')
        cfg = drive_map.load_tree_config(self.root)
        self.assertEqual((cfg.exclude, cfg.cutoff, cfg.max_depth, cfg.budget), (("*.log",), ("big",), 2, 50))

    def test_a_bad_toml_value_is_named(self) -> None:
        for body, needle in (
            ('max_depth = 0\n', "max_depth"),
            ('max_depth = "deep"\n', "max_depth"),
            ('budget = 3\n', "budget"),
            ('exclude = "*.log"\n', "exclude"),
            ('cutoff = [1, 2]\n', "cutoff"),
            ('exclude = [\n', ".drivemap.toml"),
        ):
            with self.subTest(body=body):
                self.config(body)
                with self.assertRaises(ValueError) as caught:
                    drive_map.load_tree_config(self.root)
                self.assertIn(needle, str(caught.exception))

    # -- exclude ----------------------------------------------------------------
    def test_excluded_globs_are_never_listed_or_counted(self) -> None:
        self.touch("keep.md", "debug.log", "src/b.log", "src/app.py", "private/secret.md",
                   "docs/draft-1.md", "docs/final.md")
        self.config('exclude = [".*", "*.log", "private", "docs/draft-*"]\n')
        text = self.build()
        self.assertEqual(
            _tree_paths(text),
            ["keep.md", "docs/", "docs/final.md", "src/", "src/app.py"],
        )
        self.assertIn("2 folders, 3 files", text.replace("**", ""))
        for hidden in ("debug.log", "b.log", "secret", "draft-1"):
            self.assertNotIn(hidden, text)

    def test_default_excludes_hide_dotfiles_build_output_and_dependency_trees(self) -> None:
        self.touch(".git/config", ".env", ".hyperspace/graph.db", "dist/app.js", "build/out.o",
                   "node_modules/pkg/index.js", "__pycache__/m.pyc", "notes.md")
        self.assertEqual(_tree_paths(self.build()), ["notes.md"])

    def test_an_exclude_list_in_the_toml_replaces_the_built_in_one(self) -> None:
        self.touch(".hidden/x.md", "a.log", "b.md")
        self.config('exclude = ["*.log"]\n')
        self.assertEqual(_tree_paths(self.build()), [".drivemap.toml", "b.md", ".hidden/", ".hidden/x.md"])

    def test_a_symlinked_folder_is_never_followed(self) -> None:
        outside = Path(self._tmp.name) / "elsewhere"
        outside.mkdir()
        (outside / "leak.md").write_text("x", encoding="utf-8")
        try:
            os.symlink(outside, self.root / "link", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this system will not create symlinks for this user")
        self.touch("real.md")
        text = self.build()
        self.assertNotIn("leak.md", text)
        self.assertIn("real.md", _tree_paths(text))

    # -- cutoff and depth ---------------------------------------------------------
    def test_a_cutoff_is_one_line_with_a_file_count_and_is_never_descended(self) -> None:
        self.touch("archive/a.md", "archive/sub/b.md", "archive/sub/deep/c.md", "top.md")
        self.config('cutoff = ["archive"]\n')
        text = self.build()
        self.assertEqual(_tree_paths(text), ["top.md", "archive/"])
        self.assertIn("- `archive/` — (3 files, not listed)", text)
        for hidden in ("archive/a.md", "archive/sub", "c.md"):
            self.assertNotIn(hidden, text)

    def test_a_cutoff_glob_matches_siblings_and_any_depth(self) -> None:
        self.touch("runs/x/1.md", "runs/y/2.md", "runs/y/3.md", "a/_old/4.md", "a/keep.md")
        self.config('cutoff = ["**/_old", "runs/*"]\n')
        text = self.build()
        self.assertEqual(_tree_paths(text), ["a/", "a/keep.md", "a/_old/", "runs/", "runs/x/", "runs/y/"])
        self.assertIn("- `runs/y/` — (2 files, not listed)", text)
        self.assertIn("- `a/_old/` — (1 file, not listed)", text)

    def test_an_empty_folder_is_listed_because_it_is_where_things_go(self) -> None:
        (self.root / "reference").mkdir()
        self.assertEqual(_tree_paths(self.build()), ["reference/"])

    def test_a_folder_at_max_depth_is_a_cutoff_line(self) -> None:
        self.touch("a/b/c/d.md", "a/b/e.md")
        self.assertEqual(_tree_paths(self.build()), ["a/", "a/b/", "a/b/e.md", "a/b/c/"])
        self.assertIn("- `a/b/c/` — (1 file, not listed)", self.out.read_text(encoding="utf-8"))
        self.config("max_depth = 2\n")
        text = self.build()
        self.assertEqual(_tree_paths(text), ["a/", "a/b/"])
        self.assertIn("- `a/b/` — (2 files, not listed)", text)

    def test_a_huge_cutoff_counts_up_to_the_cap_only(self) -> None:
        self.touch(*[f"big/f{i}.md" for i in range(8)])
        self.config('cutoff = ["big"]\n')
        with mock.patch.object(drive_map, "COUNT_CAP", 5):
            text = self.build()
        self.assertIn("- `big/` — (5+ files, not listed)", text)

    # -- budget -------------------------------------------------------------------
    def test_over_budget_the_deepest_levels_collapse_first_and_the_top_says_so(self) -> None:
        for top in ("one", "two"):
            self.touch(*[f"{top}/f{i}.md" for i in range(6)])
            self.touch(*[f"{top}/mid/f{i}.md" for i in range(6)])
            self.touch(*[f"{top}/mid/low/f{i}.md" for i in range(6)])
        self.config("max_depth = 4\nbudget = 40\n")
        text = self.build()
        lines = text.splitlines()
        self.assertLessEqual(len(lines), 40)
        self.assertTrue(any("over budget" in line.lower() for line in lines[:12]), lines[:12])
        self.assertIn("one/mid/low/", _tree_paths(text))
        self.assertIn("- `one/mid/low/` — (6 files, not listed)", text)
        self.assertNotIn("one/mid/low/f0.md", text)
        self.assertIn("one/f0.md", _tree_paths(text))  # the shallow levels keep their files

    def test_within_budget_nothing_is_collapsed_and_nothing_apologises(self) -> None:
        self.touch("one/mid/f.md")
        self.config("max_depth = 4\nbudget = 40\n")
        self.assertNotIn("over budget", self.build().lower())

    def test_budget_is_a_hard_ceiling_even_for_one_flat_folder(self) -> None:
        self.touch(*[f"f{i:03}.md" for i in range(100)])
        self.config("budget = 30\n")
        lines = self.build().splitlines()
        self.assertLessEqual(len(lines), 30)
        self.assertTrue(any("not listed" in line for line in lines[-3:]))

    # -- descriptions ---------------------------------------------------------------
    def test_text_after_the_dash_survives_regeneration(self) -> None:
        self.touch("reference/a.pdf", "work/app/x.md", "archive/old.md")
        self.config('cutoff = ["archive"]\n')
        self.build()
        text = self.out.read_text(encoding="utf-8")
        text = text.replace("- `reference/`", "- `reference/` — what the user brings")
        text = text.replace("- `reference/a.pdf`", "- `reference/a.pdf` — the contract")
        text = text.replace("- `archive/` — (1 file, not listed)", "- `archive/` — (1 file, not listed) closed jobs")
        self.out.write_text(text, encoding="utf-8")
        self.touch("reference/b.pdf")
        (self.root / "work" / "app" / "x.md").unlink()
        regenerated = self.build()
        self.assertIn("- `reference/` — what the user brings", regenerated)
        self.assertIn("- `reference/a.pdf` — the contract", regenerated)
        self.assertIn("- `archive/` — (1 file, not listed) closed jobs", regenerated)
        self.assertIn("- `reference/b.pdf`", regenerated)
        self.assertNotIn("work/app/x.md", regenerated)

    def test_a_description_for_a_path_that_is_gone_is_dropped(self) -> None:
        self.touch("a.md")
        self.build()
        self.out.write_text(self.out.read_text(encoding="utf-8").replace("- `a.md`", "- `a.md` — temp"), encoding="utf-8")
        (self.root / "a.md").unlink()
        self.assertNotIn("temp", self.build())

    # -- output ---------------------------------------------------------------------
    def test_output_is_a_stamp_then_totals_then_the_tree(self) -> None:
        self.touch("a/b.md", "c.md")
        with mock.patch.object(drive_map, "_now", return_value="2026-10-08 12:00 UTC"):
            lines = self.build().splitlines()
        stamp = next(i for i, line in enumerate(lines) if "Generated 2026-10-08 12:00 UTC" in line)
        totals = next(i for i, line in enumerate(lines) if "**1 folders, 2 files**" in line or "**1 folder, 2 files**" in line)
        tree = lines.index("## Tree")
        self.assertLess(stamp, tree)
        self.assertLess(totals, tree)
        self.assertEqual(_tree_paths("\n".join(lines)), ["c.md", "a/", "a/b.md"])
        self.assertTrue(lines[0].startswith("# Drive map"))

    def test_the_map_lists_itself_when_it_lives_in_the_tree_and_regeneration_is_stable(self) -> None:
        self.out = self.root / "core_text" / "drive-map.md"
        self.touch("a.md")
        with mock.patch.object(drive_map, "_now", return_value="2026-10-08 12:00 UTC"):
            first = self.build()
            second = self.build()
        self.assertIn("core_text/drive-map.md", _tree_paths(first))
        self.assertEqual(first, second)

    def test_write_tree_returns_the_numbers_the_pointer_line_needs(self) -> None:
        self.touch("a/b.md", "a/c/d.md", "e.md")
        result = drive_map.write_tree(self.root, self.out)
        self.assertEqual((result.folders, result.files), (2, 3))
        self.assertEqual(result.lines, len(self.out.read_text(encoding="utf-8").splitlines()))

    # -- the command line ---------------------------------------------------------------
    def _cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(BIN_DIR / "drive_map.py"), *args], capture_output=True, text=True)

    def test_cli_tree_honours_the_projects_exclude_list(self) -> None:
        """The whole path: a project with a .drivemap.toml, the real command, the file it writes."""
        self.touch("reference/brief.pdf", "work/app/main.py", "work/app/debug.log", "scratch/tmp.md", ".hidden/x.md")
        self.config('exclude = [".*", "*.log", "scratch"]\n')
        done = self._cli("tree", str(self.root), "--out", str(self.out))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"wrote {self.out}", done.stdout)
        self.assertRegex(done.stdout, r"\(\d+ folders?, \d+ files?, \d+ lines\)")
        text = self.out.read_text(encoding="utf-8")
        self.assertEqual(
            _tree_paths(text),
            ["reference/", "reference/brief.pdf", "work/", "work/app/", "work/app/main.py"],
        )

    def test_cli_tree_takes_a_config_from_outside_the_tree(self) -> None:
        self.touch("a.md", "b.log")
        cfg = Path(self._tmp.name) / "elsewhere.toml"
        cfg.write_text('exclude = ["*.log"]\n', encoding="utf-8")
        done = self._cli("tree", str(self.root), "--out", str(self.out), "--config", str(cfg))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(_tree_paths(self.out.read_text(encoding="utf-8")), ["a.md"])
        self.assertFalse((self.root / ".drivemap.toml").exists())

    def test_cli_tree_fails_loudly_and_writes_nothing(self) -> None:
        self.config("max_depth = 0\n")
        bad_toml = self._cli("tree", str(self.root), "--out", str(self.out))
        self.assertEqual(bad_toml.returncode, 2)
        self.assertIn("max_depth", bad_toml.stderr)
        missing = self._cli("tree", str(self.root / "nope"), "--out", str(self.out))
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(self._cli("tree", str(self.root)).returncode, 2)  # --out is required
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
