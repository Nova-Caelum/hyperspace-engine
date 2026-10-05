"""The plugin root carries no CLAUDE.md.

Claude Code 2.1.289+ warns that a `CLAUDE.md` at a plugin's root "is not loaded
as project context", and CI's `claude plugin validate --strict .` turns that
warning into a failure. The contributor notes live at `.claude/CLAUDE.md`,
which Claude Code loads as project memory for anyone working in the checkout.

Covers the tripwire row in docs/reference/tripwires.md for a root CLAUDE.md.
"""
from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_ROOT_CONTEXT_FILE = "claude.md"


class PluginRootContextFileTests(unittest.TestCase):
    def test_no_claude_md_at_the_plugin_root(self) -> None:
        # Compare case-insensitively so macOS and Windows (case-insensitive
        # file systems) and Linux agree on what counts as the same name.
        found = sorted(p.name for p in REPO_ROOT.iterdir() if p.name.lower() == _ROOT_CONTEXT_FILE)
        self.assertEqual(
            [],
            found,
            "a CLAUDE.md at the plugin root fails `claude plugin validate --strict .`; "
            "keep the contributor notes at .claude/CLAUDE.md",
        )

    def test_contributor_notes_live_in_dot_claude(self) -> None:
        notes = REPO_ROOT / ".claude" / "CLAUDE.md"
        self.assertTrue(notes.is_file(), "the contributor notes must exist at .claude/CLAUDE.md")
        self.assertIn("Hyperspace Engine", notes.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
