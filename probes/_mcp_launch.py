"""probes/_mcp_launch.py — the plugin's MCP server command, exactly as Claude
Code builds it: read a plugin root's `.mcp.json`, substitute
`${CLAUDE_PLUGIN_ROOT}` / `${CLAUDE_PROJECT_DIR}` with forward-slash paths
(Claude Code's own substitution on every OS — docs/reference/tripwires.md),
and hand back `(command, args)` to spawn with no shell. Probes and tests that
claim to start the server "as `.mcp.json` would" go through this, so a change
to `.mcp.json` is what they exercise — never a second, hand-typed copy.

On Windows an extensionless command with a sibling `<command>.cmd` resolves
to that `.cmd`, as Claude Code resolves it (PATHEXT): `.mcp.json` names
`bin/hyperspace-env`, and Windows runs `bin/hyperspace-env.cmd`. Observed with
npm and native Claude Code 2.1.296 on windows-latest, GitHub Actions run
38287396216 (Nova-Caelum/plugins, branch probe/mcp-spawn-forms). Python's own
spawn does not do this, so it is done here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _as_windows_runs_it(command: str) -> str:
    if sys.platform == "win32" and not Path(command).suffix and Path(command + ".cmd").is_file():
        return command + ".cmd"
    return command


def mcp_launch(plugin_root: str | Path, project_dir: str | Path, server: str = "hyperspace") -> tuple[str, list[str]]:
    entry = json.loads((Path(plugin_root) / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][server]
    values = {
        "${CLAUDE_PLUGIN_ROOT}": Path(plugin_root).as_posix(),
        "${CLAUDE_PROJECT_DIR}": Path(project_dir).as_posix(),
    }

    def substitute(text: str) -> str:
        for placeholder, value in values.items():
            text = text.replace(placeholder, value)
        return text

    return _as_windows_runs_it(substitute(entry["command"])), [substitute(arg) for arg in entry.get("args", [])]
