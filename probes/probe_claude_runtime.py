#!/usr/bin/env python3
"""probes/probe_claude_runtime.py — v0.1.3: the plugin as the REAL Claude Code
binary runs it, on whatever OS this probe runs on.

Everything else in this suite starts the MCP server or the SessionStart hook
itself, so it proves only what this repository believes Claude Code does.
This probe hands both to `claude`: installed from this checkout through a
local marketplace into a fresh `CLAUDE_CONFIG_DIR`, then

  1. before setup — `claude mcp list` from the project shows the `hyperspace`
     server NOT connected, and `claude --init-only` runs the SessionStart
     hook, whose output (read back from `--debug-file`) says to run
     `hyperspace-setup`;
  2. setup — the project's `.hyperspace/env` is really provisioned
     (`provision_env`), and a loop run is opened with the skills' own command
     form, `.hyperspace/env/bin/python "<plugin>/bin/loop_state.py" init …`;
  3. after setup — `claude mcp list` shows the server `Connected` (Claude
     Code's own spawner resolving `.mcp.json`'s command on this OS), and
     `claude --init-only` runs the hook successfully: primer delivered, and
     the run's `fresh_sessions` counter bumped to 1 by the hook's Python half.

No model call, no `claude -p`, no credentials: `mcp list`, `plugin install`
and `--init-only` all run unauthenticated (WINDOWS_FACTS F13, F14). The
project path contains a space. Not part of `all` — it needs `claude` on PATH.

Usage: imported by probes/run.py; PROBE = "claude_runtime"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROBE = "claude_runtime"
PLUGIN_ID = "hyperspace-engine@hyperspace-engine"
SERVER_LABEL = "plugin:hyperspace-engine:hyperspace"
HOOK_SUCCESS = "Hook SessionStart:startup (SessionStart) success"
PRIMER_MARKER = "acing-hyperspace:begin"
TIMEOUT = 240

_AUTH_ENV = ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")


def _trim(text, limit: int = 3000) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _claude(claude: str, args: list[str], *, cwd: Path, env: dict) -> dict:
    try:
        proc = subprocess.run([claude, *args], cwd=str(cwd), env=env, capture_output=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT)
        return {"args": args, "exit_code": proc.returncode, "stdout": _trim(proc.stdout),
                "stderr": _trim(proc.stderr)}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"args": args, "exit_code": None, "error": f"{type(exc).__name__}: {exc}"}


def _server_line(mcp_list_stdout: str) -> str:
    return next((line for line in mcp_list_stdout.splitlines() if SERVER_LABEL in line), "")


def _connected(line: str) -> bool:
    # Legacy Windows consoles print `√` in place of `✔` (Claude Code docs).
    return bool(re.search(r"(✔|√)\s*Connected", line)) and "Failed" not in line


def _init_only(claude: str, project: Path, env: dict, log: Path) -> dict:
    result = _claude(claude, ["--debug-file", str(log), "--init-only"], cwd=project, env=env)
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    hook_lines = [line for line in text.splitlines() if "SessionStart" in line and "Hook" in line]
    result.update({
        "hook_success": HOOK_SUCCESS in text,
        "primer_delivered": PRIMER_MARKER in text,
        "setup_pointer": "No .hyperspace/ found" in text,
        "mcp_cannot_start_line": "MCP server cannot start" in text,
        "hook_log_lines": [_trim(line, 600) for line in hook_lines[:4]],
    })
    return result


def run(out_dir, opts) -> bool:
    from hyperspace.setup.provision import provision_env
    from hyperspace.store import Store
    from hyperspace.venv_paths import portable_python

    dest = Path(out_dir) / f"{PROBE}.json"
    claude = shutil.which("claude")
    if claude is None:
        write_verdict(dest, probe=PROBE, result="FAIL", evidence={"error": "`claude` not found on PATH"})
        return False

    evidence: dict = {"platform": sys.platform}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        config_dir = tmp_path / "claude-config"
        config_dir.mkdir()
        project = tmp_path / "runtime project"
        project.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in _AUTH_ENV}
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)

        evidence["version"] = _claude(claude, ["--version"], cwd=project, env=env)
        evidence["marketplace_add"] = _claude(claude, ["plugin", "marketplace", "add", str(ROOT)], cwd=project, env=env)
        evidence["install"] = _claude(claude, ["plugin", "install", PLUGIN_ID, "--scope", "user"], cwd=project, env=env)
        installed = evidence["marketplace_add"]["exit_code"] == 0 and evidence["install"]["exit_code"] == 0

        # 1. before setup
        before = _claude(claude, ["mcp", "list"], cwd=project, env=env)
        before["server_line"] = _server_line(before.get("stdout", ""))
        evidence["mcp_list_before_setup"] = before
        evidence["hook_before_setup"] = _init_only(claude, project, env, tmp_path / "before.log")
        before_ok = (
            bool(before["server_line"]) and not _connected(before["server_line"])
            and evidence["hook_before_setup"]["hook_success"]
            and evidence["hook_before_setup"]["primer_delivered"]
            and evidence["hook_before_setup"]["setup_pointer"]
        )

        # 2. setup, with the skills' own command form for the run
        Store.init(project / ".hyperspace" / "graph.db").close()
        provisioned = provision_env(project)
        evidence["provision"] = provisioned
        (tmp_path / "input.md").write_text("Build the thing.\n", encoding="utf-8")
        env_python = portable_python(project / ".hyperspace" / "env")
        try:
            init = subprocess.run(
                [str(env_python), str(ROOT / "bin" / "loop_state.py"), "init", "--goal", "runtime-goal",
                 "--input", str(tmp_path / "input.md"), "--workspace", str(project / "hyperspace" / "runs")],
                cwd=str(project), capture_output=True, encoding="utf-8", errors="replace", timeout=120,
            )
            evidence["loop_init"] = {"command": f"{env_python} bin/loop_state.py init …",
                                     "exit_code": init.returncode, "stderr": _trim(init.stderr)}
            loop_ok = init.returncode == 0
        except OSError as exc:
            evidence["loop_init"] = {"error": f"{type(exc).__name__}: {exc}"}
            loop_ok = False

        # 3. after setup
        after = _claude(claude, ["mcp", "list"], cwd=project, env=env)
        after["server_line"] = _server_line(after.get("stdout", ""))
        evidence["mcp_list_after_setup"] = after
        evidence["hook_after_setup"] = _init_only(claude, project, env, tmp_path / "after.log")
        state_path = project / "hyperspace" / "runs" / "runtime-goal" / "loop.state.json"
        try:
            used = json.loads(state_path.read_text(encoding="utf-8"))["budget"]["fresh_sessions"]["used"]
        except (OSError, ValueError, KeyError):
            used = None
        evidence["fresh_sessions_used"] = used
        after_ok = (
            _connected(after["server_line"])
            and evidence["hook_after_setup"]["hook_success"]
            and evidence["hook_after_setup"]["primer_delivered"]
            and not evidence["hook_after_setup"]["mcp_cannot_start_line"]
            and used == 1
        )

    checks = {
        "installed": installed,
        "before_setup": before_ok,
        "provisioned": bool(provisioned.get("ok")),
        "loop_init_via_env_bin_python": loop_ok,
        "after_setup": after_ok,
    }
    evidence["checks"] = checks
    ok = all(checks.values())
    write_verdict(dest, probe=PROBE, result="PASS" if ok else "FAIL", evidence=evidence)
    return ok
