"""T1.1 — package skeleton, plugin manifests, MCP server command.

Covers: manifests parse with the exact names/versions; `hyperspace.__version__`
agrees with `plugin.json` and `pyproject.toml`; the CLI's `--version` and
unknown-subcommand paths; `.mcp.json`'s command — since v0.1.3 the project
env's own interpreter at the one spelling valid on every OS,
`.hyperspace/env/bin/python`, spawned with no shell (Windows cannot spawn a
`#!/bin/sh` launcher; WINDOWS_FACTS F1-F4).
"""
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from hyperspace.venv_paths import link_bin_to_scripts, portable_python
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
    assert data["version"] == "0.1.4"
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
    assert entry["command"] == "${CLAUDE_PROJECT_DIR}/.hyperspace/env/bin/python"
    assert entry["args"] == ["-m", "hyperspace.mcp"]
    assert "env" not in entry


def test_mcp_json_command_is_the_portable_env_interpreter(tmp_path):
    project = tmp_path / "my project"
    command, args = mcp_launch(ROOT, project)
    assert command == portable_python(project / ".hyperspace" / "env").as_posix()
    assert args == ["-m", "hyperspace.mcp"]


def test_mcp_json_command_runs_the_env_interpreter_without_a_shell(tmp_path):
    """A real venv in this OS's own layout, linked as provisioning links it;
    the substituted command, spawned as an argv list (no shell — how Claude
    Code spawns a stdio server), reaches that venv's interpreter."""
    project = tmp_path / "my project"
    env_dir = project / ".hyperspace" / "env"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(env_dir)], check=True, capture_output=True)
    ok, message = link_bin_to_scripts(env_dir)
    assert ok, message
    command, _args = mcp_launch(ROOT, project)
    proc = subprocess.run([command, "-c", "import sys; print(sys.prefix)"], capture_output=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    assert Path(proc.stdout.strip()).resolve() == env_dir.resolve()


def test_mcp_json_command_fails_loudly_without_the_env(tmp_path):
    """No environment, no process: the spawn itself fails (Claude Code shows
    "failed to connect"); the SessionStart hook names the missing path and
    the fix (tests/test_hooks.py::SetupStateTests)."""
    command, args = mcp_launch(ROOT, tmp_path / "never set up")
    with pytest.raises(FileNotFoundError):
        subprocess.run([command, *args], capture_output=True)


def test_pyproject_names_and_versions():
    data = _read_pyproject()
    project = data["project"]
    assert project["name"] == "hyperspace-engine"
    assert project["version"] == "0.1.4"
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
    assert hyperspace.__version__ == "0.1.4"
    assert hyperspace.__version__ == plugin["version"]
    assert hyperspace.__version__ == pyproject["project"]["version"]


def test_cli_version_flag(capsys):
    sys.path.insert(0, str(ROOT))
    from hyperspace import cli

    rc = cli.main(["--version"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "0.1.4" in out


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
