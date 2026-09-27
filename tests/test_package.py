"""T1.1 — package skeleton, plugin manifests, MCP launcher.

Covers: manifests parse with the exact names/versions; `hyperspace.__version__`
agrees with `plugin.json` and `pyproject.toml`; the CLI's `--version` and
unknown-subcommand paths; the launcher script's exec target and its refusal
message when the isolated env is missing.
"""
import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read_json(rel):
    return json.loads((ROOT / rel).read_text())


def _read_pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


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
    assert data["version"] == "0.1.2"
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
    assert entry["command"] == "${CLAUDE_PLUGIN_ROOT}/bin/hyperspace-mcp"
    assert "env" not in entry


def test_pyproject_names_and_versions():
    data = _read_pyproject()
    project = data["project"]
    assert project["name"] == "hyperspace-engine"
    assert project["version"] == "0.1.2"
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
    assert hyperspace.__version__ == "0.1.2"
    assert hyperspace.__version__ == plugin["version"]
    assert hyperspace.__version__ == pyproject["project"]["version"]


def test_cli_version_flag(capsys):
    sys.path.insert(0, str(ROOT))
    from hyperspace import cli

    rc = cli.main(["--version"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "0.1.2" in out


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


def test_launcher_exec_target_string():
    launcher = (ROOT / "bin" / "hyperspace-mcp").read_text()
    assert "-m hyperspace.mcp" in launcher
    assert 'exec "$ROOT/.hyperspace/env/bin/python"' in launcher


def test_launcher_refuses_without_env(tmp_path):
    empty_project_dir = tmp_path / "empty-project"
    empty_project_dir.mkdir()
    result = subprocess.run(
        ["sh", str(ROOT / "bin" / "hyperspace-mcp")],
        env={"CLAUDE_PROJECT_DIR": str(empty_project_dir), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert ".hyperspace/env" in result.stderr
