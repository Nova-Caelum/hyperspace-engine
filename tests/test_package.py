"""T1.1 — package skeleton, plugin manifests, MCP server command.

Covers: manifests parse with the exact names/versions; `hyperspace.__version__`
agrees with `plugin.json` and `pyproject.toml`; the CLI's `--version` and
unknown-subcommand paths; `.mcp.json`'s command — since v1.0.3 the plugin's
own `bin/hyperspace-env`, spelled `${CLAUDE_PLUGIN_ROOT}/<file>` with nothing
computed, which starts the project's env only through
`hyperspace/provenance.py` (tests/test_provenance.py). Claude Code runs it as
a `#!/bin/sh` script on macOS/Linux and runs the sibling `.cmd` on Windows.
"""
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from probes._mcp_launch import mcp_launch

ROOT = Path(__file__).resolve().parents[1]


def _read_json(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _read_pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_marketplace_json_shape():
    data = _read_json(".claude-plugin/marketplace.json")
    assert data["name"] == "hyperspace-engine"
    assert data["owner"]["name"] == "Nova Caelum"
    assert isinstance(data["description"], str) and data["description"]
    plugins = data["plugins"]
    assert len(plugins) == 1
    assert plugins[0]["name"] == "hyperspace-engine"
    assert plugins[0]["source"] == "./"
    assert isinstance(plugins[0]["description"], str) and plugins[0]["description"]


def test_plugin_json_shape():
    data = _read_json(".claude-plugin/plugin.json")
    assert data["name"] == "hyperspace-engine"
    assert data["version"] == "1.0.2"
    assert isinstance(data["description"], str) and data["description"]
    assert data["author"]["name"] == "Nova Caelum"
    assert data["author"]["url"] == "https://novacaelum.com"
    assert data["license"] == "MIT"
    assert "hyperspace-engine" in data.get("homepage", "") or "hyperspace-engine" in data.get("repository", "")
    assert isinstance(data["keywords"], list) and data["keywords"]


def test_mcp_json_shape():
    data = _read_json(".mcp.json")
    assert set(data["mcpServers"].keys()) == {"hyperspace"}
    entry = data["mcpServers"]["hyperspace"]
    assert entry["command"] == "${CLAUDE_PLUGIN_ROOT}/bin/hyperspace-env"
    assert entry["args"] == ["-m", "hyperspace.mcp"]
    assert "env" not in entry


def test_mcp_json_names_no_project_path():
    """The Anthropic directory scan requires every command to be spelled
    literally `${CLAUDE_PLUGIN_ROOT}/<file>`; a `${CLAUDE_PROJECT_DIR}` path
    is also exactly what started a folder's own interpreter before 1.0.3."""
    assert "${CLAUDE_PROJECT_DIR}" not in (ROOT / ".mcp.json").read_text(encoding="utf-8")


def test_mcp_entry_files_exist_with_their_line_endings():
    posix = (ROOT / "bin" / "hyperspace-env").read_bytes()
    windows = (ROOT / "bin" / "hyperspace-env.cmd").read_bytes()
    assert posix.startswith(b"#!/bin/sh\n") and b"\r" not in posix
    assert windows.count(b"\n") == windows.count(b"\r\n") > 0, "hyperspace-env.cmd must be CRLF throughout"


def test_mcp_entry_files_hand_over_to_provenance_and_name_nothing_in_the_project():
    """Both entry files only find the computer's own Python and run
    `provenance.py run`; no line of code (comments aside) names the project."""
    for name, comment in (("hyperspace-env", "#"), ("hyperspace-env.cmd", "rem")):
        code = [
            line for line in (ROOT / "bin" / name).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().lower().startswith(comment)
        ]
        joined = "\n".join(code)
        assert "provenance.py\" run -- " in joined, name
        assert ".hyperspace" not in joined and "CLAUDE_PROJECT_DIR" not in joined, name


def test_posix_entry_file_is_executable_in_git():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout, so there is no index mode to read")
    entry = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-s", "bin/hyperspace-env"],
        capture_output=True, encoding="utf-8", check=True,
    ).stdout
    assert entry.startswith("100755 "), entry


def test_mcp_json_command_is_the_plugins_launcher(tmp_path):
    command, args = mcp_launch(ROOT, tmp_path / "my project")
    expected = (ROOT / "bin" / "hyperspace-env").as_posix() + (".cmd" if sys.platform == "win32" else "")
    assert command == expected
    assert args == ["-m", "hyperspace.mcp"]


def test_mcp_json_command_without_an_env_exits_missing_with_one_line(tmp_path):
    """No environment, no Python started from the project: the launcher says
    so in one line and exits 4 (Claude Code shows "failed to connect"; the
    SessionStart hook names the fix too — tests/test_hooks.py)."""
    project = tmp_path / "never set up"
    project.mkdir()
    command, args = mcp_launch(ROOT, project)
    proc = subprocess.run(
        [command, *args], cwd=str(project), env={**_scratch_env(tmp_path), "CLAUDE_PROJECT_DIR": str(project)},
        stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=120,
    )
    assert proc.returncode == 4, (proc.stdout, proc.stderr)
    assert proc.stdout == ""
    assert len(proc.stderr.strip().splitlines()) == 1
    assert "hyperspace-setup" in proc.stderr


def _scratch_env(tmp_path: Path) -> dict:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}


def test_pyproject_names_and_versions():
    data = _read_pyproject()
    project = data["project"]
    assert project["name"] == "hyperspace-engine"
    assert project["version"] == "1.0.2"
    assert project["requires-python"] == ">=3.11"
    assert project["license"] == "MIT"
    deps = project["dependencies"]
    joined = "\n".join(deps)
    assert "pydantic>=2.11" in joined
    assert "pydantic-graph>=2.51" in joined
    assert "pydantic-ai-slim[anthropic,openrouter]>=2.40" in joined
    assert "mcp>=2.1" in joined
    assert project["optional-dependencies"]["dev"] == ["pytest>=8"]
    assert project["scripts"]["hyperspace"] == "hyperspace.cli:main"


def test_version_agrees_across_sources():
    sys.path.insert(0, str(ROOT))
    import hyperspace

    plugin = _read_json(".claude-plugin/plugin.json")
    pyproject = _read_pyproject()
    assert hyperspace.__version__ == "1.0.2"
    assert hyperspace.__version__ == plugin["version"]
    assert hyperspace.__version__ == pyproject["project"]["version"]


def test_cli_version_flag(capsys):
    sys.path.insert(0, str(ROOT))
    from hyperspace import cli

    rc = cli.main(["--version"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1.0.2" in out


def test_cli_unknown_subcommand_exits_2(capsys):
    sys.path.insert(0, str(ROOT))
    from hyperspace import cli

    rc = cli.main(["nonexistent"])
    assert rc == 2
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "no subcommands installed yet" in combined
    assert "init" in combined
    assert "serve" in combined
    assert "doctor" in combined


def test_cli_absent_subcommand_exits_2(capsys):
    sys.path.insert(0, str(ROOT))
    from hyperspace import cli

    rc = cli.main([])
    assert rc == 2
