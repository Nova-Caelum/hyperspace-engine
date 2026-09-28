"""Tests for the couplings named in docs/reference/tripwires.md (hyperspace-
engine v0.1.1 part A, task 5 — "turn every tripwire you can into a test").

Each class here is the "Test" column for one or more rows of that table.
Where a row cites an existing test elsewhere in this repo (`test_drive_map.py`,
`test_port.py`, `probe_gear_names.py`, `probe_whole_path.py`,
`probes/check_ui_build.py`), this file does not duplicate it — see the table
for which row maps to which check.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_07 = REPO_ROOT / "docs" / "07_troubleshooting.md"
BIN_DIR = REPO_ROOT / "bin"


def _iter_markdown_files() -> list[Path]:
    files = [REPO_ROOT / "README.md", REPO_ROOT / "CLAUDE.md"]
    files += sorted((REPO_ROOT / "docs").rglob("*.md"))
    files += sorted((REPO_ROOT / "skills").rglob("*.md"))
    return [f for f in files if f.is_file()]


# ── (a) markdown links resolve ──────────────────────────────────────────────

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_IMG_SRC_RE = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"')


def _is_external(target: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target)) or target.startswith("//")


class MarkdownLinkTests(unittest.TestCase):
    """docs/reference/tripwires.md row: 'Renaming a doc file cited by name
    elsewhere' — every relative link in README.md, CLAUDE.md and docs/**/*.md
    must resolve to a real file (fragments and query strings stripped;
    absolute URLs and mailto: skipped)."""

    def test_every_relative_link_resolves(self) -> None:
        broken: list[str] = []
        for md_file in [REPO_ROOT / "README.md", REPO_ROOT / "CLAUDE.md"] + sorted(
            (REPO_ROOT / "docs").rglob("*.md")
        ):
            text = md_file.read_text(encoding="utf-8")
            targets = _LINK_RE.findall(text) + _IMG_SRC_RE.findall(text)
            for target in targets:
                target = target.strip()
                if not target or _is_external(target) or target.startswith("#"):
                    continue
                path_part = target.split("#", 1)[0]
                resolved = (md_file.parent / path_part).resolve()
                if not resolved.exists():
                    broken.append(f"{md_file.relative_to(REPO_ROOT)} -> {target}")
        self.assertEqual([], broken, "broken relative links:\n" + "\n".join(broken))


# ── (b) plugin name + .mcp.json server key compose the mcp tool prefix ─────


class McpToolPrefixTests(unittest.TestCase):
    """docs/reference/tripwires.md row: plugin `name` + `.mcp.json` server
    key composing `mcp__plugin_<name>_<server>__*`. Computed independently of
    every hand-typed copy, then asserted present in each one."""

    def _expected_prefix(self) -> str:
        plugin = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        mcp = json.loads((REPO_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        server_name = next(iter(mcp["mcpServers"]))
        return f"mcp__plugin_{plugin['name']}_{server_name}__"

    def test_prefix_matches_the_generated_mcp_tools_doc(self) -> None:
        expected = self._expected_prefix()
        rendered = (REPO_ROOT / "docs" / "reference" / "mcp-tools.md").read_text(encoding="utf-8")
        self.assertIn(expected, rendered)

    def test_prefix_matches_the_whole_path_probes_allowed_tools(self) -> None:
        expected = self._expected_prefix()
        probe_text = (REPO_ROOT / "probes" / "probe_whole_path.py").read_text(encoding="utf-8")
        self.assertIn(expected, probe_text)


# ── (c) docs/07 refusal strings still exist byte-identical in bin/ ─────────

# `<...>`-bracketed placeholders (`<path>`, `<id>`, ...) AND a literal `...`
# ellipsis — docs/07 uses the latter at least once to elide across two
# genuinely different node_gates.py refusal branches in one table row (the
# `completed_by` row), not to elide a single message's dynamic middle.
_PLACEHOLDER_RE = re.compile(r"<[^>]+>|\.\.\.")
_MIN_SEGMENT_LEN = 15
# Scope: the four gate-message tables. Later sections (Exit 2 usage, Exit 3
# HOLD) quote CLI examples and situations, not node_gates.py constants — a
# different kind of string, out of this row's scope.
_SCOPE_START = "## 1. Understand gate"
_SCOPE_END = "## 5. Exit 2"

# node_gates.py wraps several message constants across two adjacent string
# literals for line length (`"...part one "` \n `"part two..."`), which
# Python concatenates at compile time but which are NOT contiguous in the
# raw source text this test scans. Merge same-quote-char literals separated
# only by whitespace before searching, so a source-formatting line wrap is
# never mistaken for a wording drift.
_ADJACENT_STRING_LITERALS_RE = re.compile(r"""(["'])\s+\1""")


def _docs07_scoped_text() -> str:
    text = DOCS_07.read_text(encoding="utf-8")
    start = text.index(_SCOPE_START)
    end = text.index(_SCOPE_END)
    return text[start:end]


def _longest_placeholder_free_segment(message: str) -> str:
    segments = _PLACEHOLDER_RE.split(message)
    return max((s.strip() for s in segments), key=len, default="")


class Docs07RefusalTests(unittest.TestCase):
    """docs/reference/tripwires.md row: refusal strings quoted verbatim in
    docs/07, sourced from bin/node_gates.py. Messages carry <path>/<id>-style
    placeholders and several call sites in bin/ compose them as f-strings, so
    this checks the longest placeholder-free segment of each quoted message
    (>= 15 chars) is present verbatim somewhere in the concatenated bin/*.py
    source — not full-string equality, which a live placeholder value would
    never satisfy anyway."""

    def test_message_column_excerpts_appear_in_bin(self) -> None:
        scoped = _docs07_scoped_text()
        messages = [
            m.group(1)
            for m in re.finditer(r"^\|\s*`([^`]+)`", scoped, flags=re.MULTILINE)
        ]
        self.assertGreater(len(messages), 5, "expected several quoted refusal messages in docs/07")

        bin_source = "\n".join(
            p.read_text(encoding="utf-8") for p in sorted(BIN_DIR.glob("*.py"))
        )
        bin_source = _ADJACENT_STRING_LITERALS_RE.sub("", bin_source)

        missing: list[str] = []
        for message in messages:
            segment = _longest_placeholder_free_segment(message)
            if len(segment) < _MIN_SEGMENT_LEN:
                continue
            if segment not in bin_source:
                missing.append(f"{segment!r} (from message {message!r})")
        self.assertEqual([], missing, "docs/07 excerpts not found in bin/*.py:\n" + "\n".join(missing))


# ── skill and bin/ name references resolve ──────────────────────────────────

_SKILL_NAME_RE = re.compile(r"\bgear[0-9]+-[a-z]+(?:-[a-z]+)*\b|\bacing-hyperspace\b|\bhyperspace-setup\b")
_BIN_SCRIPT_RE = re.compile(r"\bbin/([A-Za-z_][A-Za-z0-9_]*\.py)\b")


class SkillNameReferenceTests(unittest.TestCase):
    """docs/reference/tripwires.md row: skill directory name = the skill's
    own frontmatter name = every prose reference to it. probe_gear_names.py
    checks the directory set is a subset of what's expected; this checks the
    other direction — every shape-matching prose mention (including this
    plugin's own new `hooks/session-start.sh`) names a skill that actually
    exists."""

    def test_every_skill_name_shaped_mention_resolves(self) -> None:
        skill_dirs = {p.name for p in (REPO_ROOT / "skills").iterdir() if p.is_dir()}
        sources = _iter_markdown_files() + [REPO_ROOT / "hooks" / "session-start.sh", REPO_ROOT / "hooks" / "session_start.py"]

        missing: list[str] = []
        for src in sources:
            if not src.is_file():
                continue
            text = src.read_text(encoding="utf-8", errors="replace")
            for match in _SKILL_NAME_RE.finditer(text):
                name = match.group(0)
                if name not in skill_dirs:
                    missing.append(f"{src.relative_to(REPO_ROOT)}: {name!r}")
        self.assertEqual([], missing, "prose names a skill directory that does not exist:\n" + "\n".join(missing))


class BinScriptReferenceTests(unittest.TestCase):
    """docs/reference/tripwires.md row: a skill's prose naming a bin/<script>
    it invokes. Every such mention across skills/, docs/, README.md and
    CLAUDE.md must name a file that exists."""

    def test_every_bin_script_mention_resolves(self) -> None:
        sources = _iter_markdown_files()
        missing: list[str] = []
        for src in sources:
            text = src.read_text(encoding="utf-8", errors="replace")
            for match in _BIN_SCRIPT_RE.finditer(text):
                script_name = match.group(1)
                if not (BIN_DIR / script_name).is_file():
                    missing.append(f"{src.relative_to(REPO_ROOT)}: bin/{script_name}")
        self.assertEqual([], missing, "prose names a bin/ script that does not exist:\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()


# ── docs/07 §8 (setup and Windows) quotes the runtime's own text ────────────

_SETUP_SCOPE_START = "## 8. Setup, the environment, and Windows"


class Docs07SetupMessageTests(unittest.TestCase):
    """docs/reference/tripwires.md row: the setup/Windows messages quoted in
    docs/07 §8 come from the hook, `doctor`, the launcher templates and the
    CLI — rewording one there must fail here, not strand the doc row."""

    def test_setup_section_excerpts_appear_in_their_sources(self) -> None:
        text = DOCS_07.read_text(encoding="utf-8")
        scoped = text[text.index(_SETUP_SCOPE_START):]
        scoped = scoped[: scoped.index("\n---")]
        messages = [m.group(1) for m in re.finditer(r"^\|\s*`([^`]+)`", scoped, flags=re.MULTILINE)]
        self.assertGreaterEqual(len(messages), 6)
        sources = [REPO_ROOT / "hooks" / "session-start.sh", REPO_ROOT / "hooks" / "session_start.py"]
        sources += sorted((REPO_ROOT / "hyperspace").rglob("*.py"))
        sources += sorted((REPO_ROOT / "hyperspace" / "setup" / "launcher_templates").iterdir())
        corpus = "\n".join(p.read_text(encoding="utf-8") for p in sources if p.is_file())
        corpus = _ADJACENT_STRING_LITERALS_RE.sub("", corpus)
        # The Store placeholder's text is Windows' own, quoted for recognition.
        external = {"Python was not found; run without arguments to install from the Microsoft Store"}
        missing = [
            m for m in messages
            if m not in external and _longest_placeholder_free_segment(m) not in corpus
        ]
        self.assertEqual([], missing, "docs/07 §8 excerpts not found in their sources:\n" + "\n".join(missing))
