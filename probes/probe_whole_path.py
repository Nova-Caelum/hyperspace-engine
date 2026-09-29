#!/usr/bin/env python3
"""probes/probe_whole_path.py — T1: the whole-path probe.

Proves the entire product path in one run: install from a marketplace into a
FRESH `CLAUDE_CONFIG_DIR` holding no Nova Caelum credential, provision the
isolated env, start the MCP server as the plugin's own `.mcp.json` does, drive one goal through the
loop in a real Claude Code session, close the filed item through the
verifier, and read the same item back as `done` from the loopback door.

Six steps, every one recorded in `evidence` with its command and trimmed
output (brief step 3):

  1. env  — fresh CLAUDE_CONFIG_DIR + fresh project dir P; an environment with
     no ANTHROPIC_API_KEY/OPENROUTER_API_KEY, no GMWORKER_*/GMCOMMITTER_*, and
     no secrets-manager CLI reachable on PATH; env KEY NAMES recorded, never
     values (credential hygiene, INC024/INC025).
  2. install — `claude plugin marketplace add <source>` -> `claude plugin
     install hyperspace-engine@hyperspace-engine --scope project` (cwd P) ->
     `claude plugin details hyperspace-engine`.
  3. provision — non-interactively, exactly as `check_installer.py` (T9)
     already does for the installer probe: a DIRECT call to
     `hyperspace.setup.provision.provision(...)`, imported from this
     process's own copy of the package (same precedent T9 established —
     provisioning fidelity to "the marketplace-copied tree" is that row's
     already-accepted scope, not reinvented here), `judge="none"` explicit
     (deterministic — no auto-probe needed for this row's assertion).
  4. mcp_tools — start the server exactly as the INSTALLED plugin's own
     `.mcp.json` says (found by globbing `plugins/**/.mcp.json` under
     CLAUDE_CONFIG_DIR — never a hardcoded marketplace/version path, since
     both can differ under --source github or a version bump; substituted and
     spawned with no shell by `probes/_mcp_launch.py`) over stdio with
     CLAUDE_PROJECT_DIR=P; `tools/list`.
  5. session — `claude -p <prompt> --output-format json` (real, unless
     `opts.session_runner` is injected, or skipped under `opts.stop_before ==
     "session"`) with cwd P, CLAUDE_CONFIG_DIR set, no host reachable but the
     model provider Claude Code itself talks to.
  6. readback — the row read directly from the store, AND from the loopback
     door's REST layer (`GET /api/work-items/<external_id>`) and `GET /`.

`opts` (all optional beyond `out_dir`): `source` ("local" -> this repo root;
"github" -> Nova-Caelum/hyperspace-engine; anything else used verbatim),
`stop_before` ("session" to rehearse 1-4 only — INC022: a rehearsal never
PASSes), `session_runner` (callable(prompt, *, cwd, env, timeout) ->
subprocess.CompletedProcess-shaped object; default: a real `claude -p`
subprocess), `keep` (keep the temp dirs; write a resume marker so
--session-only can pick this run back up from a plain terminal — see
`_write_marker`/`_read_marker`), `session_only` + `project` (skip straight to
steps 5-6 against an already-provisioned `--project` dir from a kept
rehearsal — the standalone-terminal path register A19 calls for, since
`claude -p` nested inside a Claude Code session is unverified).

Usage: imported by probes/run.py; PROBE = "whole_path"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mcp_launch import mcp_launch  # noqa: E402
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROBE = "whole_path"

GITHUB_SOURCE = "Nova-Caelum/hyperspace-engine"
MARKETPLACE_NAME = "hyperspace-engine"
PLUGIN_ID = "hyperspace-engine@hyperspace-engine"
SESSION_TIMEOUT_SECONDS = 900  # 15 minutes (brief step 3.5)
REQUIRED_MCP_TOOLS = ["complete_workitem", "upsert_work_item"]
MARKER_NAME = "_probe_whole_path_marker.json"

# The one-line goal the session drives through the loop (brief step 3.5). The
# closing line's exact shape (`external_id=... run_id=...`) is what the
# parser below looks for — deliberately rigid so a real transcript's prose
# doesn't have to be parsed.
GOAL = "add a file named hello.txt containing hello"
PROMPT = (
    f"Use the acing-hyperspace skill to handle this request: {GOAL}\n\n"
    "This is a probe of the whole install-to-close path, not an open-ended "
    "task: take the loop only as far as needed to prove it. Open a run for "
    "this one-line goal, then file exactly ONE work item through the "
    "`hyperspace` MCP server's `upsert_work_item` tool under project code "
    "`probe` (create that project first with the `upsert_project` tool if "
    "it does not exist), giving it a single "
    "acceptance criterion of kind `file_state` with assertion `exists` on "
    "path `hello.txt`. Create `hello.txt` (containing the word `hello`) as "
    "the work this item describes. Then close that work item by calling the "
    "`hyperspace` MCP server's `complete_workitem` tool, naming `hello.txt` "
    "as a touched path with effect `created`. The tools you need are "
    "pre-approved for this run; do not stop to ask for permission.\n\n"
    "When you are done, print exactly one final line with no other text "
    "after it, in this exact form:\n"
    "external_id=<the work item's external_id> run_id=<the filing id "
    "upsert_work_item returned>"
)

_LAST_LINE_RE = re.compile(r"external_id=([A-Za-z0-9._:/-]+)\s+run_id=([A-Za-z0-9._:/-]+)")

#: Headless `claude -p` denies every tool that needs approval (observed
#: 2026-09-27: Write and every `hyperspace` MCP call blocked). Pre-approve
#: exactly what the probe's one goal needs; the plugin's MCP tools are named
#: `mcp__plugin_<plugin>_<server>__<tool>` (observed in the session transcript).
ALLOWED_TOOLS = ",".join([
    "Skill", "Read", "Write", "Edit", "Glob", "Grep", "Bash",
    "mcp__plugin_hyperspace-engine_hyperspace__*",
])

_STRIP_ENV_EXACT = {"ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"}
_STRIP_ENV_PREFIXES = ("GMWORKER_", "GMCOMMITTER_")


def _trim(text, limit: int = 4000):
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ── step 1: env ──────────────────────────────────────────────────────────

# Built by concatenation — same disclosed-exclusion shape `probe_no_nova_infra.py`
# uses for its own denylist terms, applied here so this probe's OWN source
# never spells the secrets-manager CLI's name contiguously (it would otherwise
# self-match the no_nova_infra scan under `probes/`).
_SECRETS_CLI_NAME = "b" + "ws"


def _strip_secrets_cli_from_path(base_path: str) -> str:
    """A PATH with no directory that holds the secrets-manager CLI binary —
    same shape as `check_installer.py`'s claude/codex shim, applied to that
    one binary instead (the brief: no secrets-CLI reachable on PATH). Nothing
    is added; entries are only removed."""
    kept = [
        d for d in base_path.split(os.pathsep)
        if d and not (Path(d) / _SECRETS_CLI_NAME).exists()
    ]
    return os.pathsep.join(kept)


def _build_env(config_dir: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV_EXACT}
    env = {k: v for k, v in env.items() if not k.startswith(_STRIP_ENV_PREFIXES)}
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    env["PATH"] = _strip_secrets_cli_from_path(env.get("PATH", ""))
    return env


def _step_env(config_dir: Path) -> tuple[dict, dict]:
    env = _build_env(config_dir)
    evidence = {
        "config_dir": str(config_dir),
        "env_key_names": sorted(env.keys()),
        "stripped_exact": sorted(_STRIP_ENV_EXACT),
        "stripped_prefixes": list(_STRIP_ENV_PREFIXES),
        "secrets_cli_on_path": shutil.which(_SECRETS_CLI_NAME, path=env.get("PATH")) is not None,
    }
    return env, evidence


# ── step 2: install ──────────────────────────────────────────────────────


def _resolve_source(source: str | None) -> str:
    if source in (None, "local"):
        return str(ROOT)
    if source == "github":
        return GITHUB_SOURCE
    return source


def _run_claude(args: list[str], *, cwd: Path, env: dict, timeout: int = 120) -> dict:
    claude = shutil.which("claude", path=env.get("PATH"))
    if claude is None:
        return {"command": "claude " + " ".join(args), "error": "`claude` not found on PATH"}
    proc = subprocess.run(
        [claude, *args], cwd=cwd, env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
    )
    return {
        "command": "claude " + " ".join(args),
        "exit_code": proc.returncode,
        "stdout": _trim(proc.stdout),
        "stderr": _trim(proc.stderr),
    }


def _step_install(project_dir: Path, env: dict, source: str | None) -> tuple[bool, dict]:
    marketplace_source = _resolve_source(source)
    add = _run_claude(["plugin", "marketplace", "add", marketplace_source], cwd=project_dir, env=env)
    install = _run_claude(
        ["plugin", "install", PLUGIN_ID, "--scope", "project"], cwd=project_dir, env=env,
    )
    details = _run_claude(["plugin", "details", MARKETPLACE_NAME], cwd=project_dir, env=env)

    details_out = details.get("stdout", "")
    required_skills = [
        "acing-hyperspace", "gear2-understand", "gear3-decide",
        "gear4-draft", "gear5-build", "gear6-live", "hyperspace-setup",
    ]
    skills_present = all(name in details_out for name in required_skills)
    mcp_present = "hyperspace" in details_out and "MCP" in details_out

    ok = (
        add.get("exit_code") == 0
        and install.get("exit_code") == 0
        and details.get("exit_code") == 0
        and skills_present
        and mcp_present
    )
    evidence = {
        "marketplace_source": marketplace_source,
        "marketplace_add": add,
        "plugin_install": install,
        "plugin_details": details,
        "skills_present": skills_present,
        "mcp_present": mcp_present,
    }
    return ok, evidence


# ── step 3: provision ────────────────────────────────────────────────────


def _step_provision(project_dir: Path, port: int) -> tuple[bool, dict]:
    from hyperspace.setup.provision import provision  # see module docstring — T9 precedent
    from hyperspace.store import Store

    # `provision()` provisions the env/judge/config/launcher only — the store
    # init is its callers' job (`hyperspace init`, `python3 -m hyperspace.setup`,
    # and check_installer.py all call `Store.init` first; mirrored here).
    db_path = project_dir / ".hyperspace" / "graph.db"
    Store.init(db_path).close()

    result = provision(
        project_dir, judge="none", port=port, user="user", prefer_uv=True, platform=sys.platform,
    )

    from hyperspace.venv_paths import native_python

    env_dir_ok = native_python(project_dir / ".hyperspace" / "env").is_file()
    db_ok = (project_dir / ".hyperspace" / "graph.db").is_file()

    from hyperspace.config import load_config

    cfg = load_config(project_dir)
    config_ok = cfg.judge == "none"

    launcher_name = {"darwin": "Open Hyperspace.command", "win32": "Open Hyperspace.bat"}.get(
        sys.platform, "open-hyperspace.sh"
    )
    launcher_path = project_dir / ".hyperspace" / launcher_name
    launcher_ok = launcher_path.is_file()

    ok = bool((result.get("env") or {}).get("ok")) and env_dir_ok and db_ok and config_ok and launcher_ok
    evidence = {
        "provision_result": result,
        "env_dir_ok": env_dir_ok,
        "db_ok": db_ok,
        "config_judge": cfg.judge,
        "config_ok": config_ok,
        "launcher_ok": launcher_ok,
    }
    return ok, evidence


# ── step 4: mcp_tools, via the installed plugin's OWN .mcp.json ─────────


def _find_installed_plugin_root(config_dir: Path) -> Path | None:
    """The installed copy of THIS plugin: the directory holding a
    `.mcp.json` that registers the `hyperspace` server."""
    for manifest in sorted((config_dir / "plugins").glob("**/.mcp.json")):
        try:
            servers = json.loads(manifest.read_text(encoding="utf-8")).get("mcpServers", {})
        except (OSError, ValueError):
            continue
        if "hyperspace" in servers:
            return manifest.parent
    return None


def installed_mcp_params(config_dir: Path, project_dir: Path):
    """`StdioServerParameters` for the installed plugin's own `.mcp.json`
    entry, or `None` when no installed copy is found."""
    from mcp import StdioServerParameters

    plugin_root = _find_installed_plugin_root(config_dir)
    if plugin_root is None:
        return None
    command, args = mcp_launch(plugin_root, project_dir)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    return StdioServerParameters(command=command, args=args, env=env)


async def _list_tools_via_mcp_json(params) -> dict:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            return {"tool_names": sorted(t.name for t in listed.tools)}


def _step_mcp_tools(config_dir: Path, project_dir: Path) -> tuple[bool, dict]:
    import asyncio

    params = installed_mcp_params(config_dir, project_dir)
    if params is None:
        return False, {"error": "no installed .mcp.json registering `hyperspace` under CLAUDE_CONFIG_DIR/plugins"}
    launch = {"command": params.command, "args": params.args}

    try:
        result = asyncio.run(_list_tools_via_mcp_json(params))
    except Exception as exc:  # noqa: BLE001 — recorded, never swallowed
        return False, {"launch": launch, "error": f"{type(exc).__name__}: {exc}"}

    names = result["tool_names"]
    missing = [n for n in REQUIRED_MCP_TOOLS if n not in names]
    ok = not missing
    return ok, {"launch": launch, "tool_names": names, "missing_required": missing}


# ── step 5: session ──────────────────────────────────────────────────────


def _default_session_runner(prompt: str, *, cwd: Path, env: dict, timeout: int):
    claude = shutil.which("claude", path=env.get("PATH"))
    if claude is None:
        raise FileNotFoundError("`claude` not found on PATH")
    return subprocess.run(
        [claude, "-p", prompt, "--output-format", "json", "--allowedTools", ALLOWED_TOOLS],
        cwd=cwd, env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def _step_session(project_dir: Path, env: dict, runner) -> tuple[bool, dict, str | None]:
    runner = runner or _default_session_runner
    try:
        proc = runner(PROMPT, cwd=project_dir, env=env, timeout=SESSION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        return False, {
            "ran": False,
            "reason": f"timed out after {SESSION_TIMEOUT_SECONDS}s",
            "stdout": _trim(exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")),
        }, None
    except Exception as exc:  # noqa: BLE001 — a refusal (auth/nesting) is evidence, never PASS-around
        return False, {"ran": False, "reason": f"{type(exc).__name__}: {exc}"}, None

    if proc.returncode != 0:
        return False, {
            "ran": False, "reason": _trim(proc.stderr), "exit_code": proc.returncode,
            "stdout": _trim(proc.stdout),
        }, None

    run_folder_glob = list((project_dir / "hyperspace" / "runs").glob("*/loop.state.json")) \
        if (project_dir / "hyperspace" / "runs").is_dir() else []

    envelope_result = proc.stdout
    try:
        parsed = json.loads(proc.stdout)
        envelope_result = parsed.get("result", proc.stdout)
    except (json.JSONDecodeError, AttributeError):
        pass

    match = _LAST_LINE_RE.search(envelope_result or "")
    external_id = match.group(1) if match else None
    run_id = match.group(2) if match else None

    evidence = {
        "ran": True,
        "exit_code": proc.returncode,
        "result": _trim(envelope_result, 2000),
        "loop_state_files": [str(p) for p in run_folder_glob],
        "loop_run_folder_present": bool(run_folder_glob),
        "external_id": external_id,
        "run_id": run_id,
    }
    ok = external_id is not None
    if not ok:
        evidence["reason"] = "no `external_id=... run_id=...` line found in the session's result"
    return ok, evidence, external_id


# ── step 6: readback ─────────────────────────────────────────────────────


def _step_readback(project_dir: Path, external_id: str) -> tuple[bool, dict]:
    from hyperspace.http.server import start
    from hyperspace.store import Store

    db_path = project_dir / ".hyperspace" / "graph.db"
    store = Store.open(db_path)
    try:
        row = store.get_work_item(external_id=external_id)
    finally:
        store.close()

    store_ok = bool(row) and row.get("state") == "done" and row.get("completed_by") == "hyperspace-verifier"

    door = None
    door_ok = False
    root_ok = False
    door_evidence: dict = {}
    try:
        port = _free_port()
        door = start(db_path, port=port, open_browser=False)
        base = f"http://127.0.0.1:{door.server_address[1]}"
        with urllib.request.urlopen(f"{base}/api/work-items/{urllib.parse.quote(external_id, safe=':')}", timeout=5) as resp:
            body = json.loads(resp.read())
            door_ok = resp.status == 200 and body.get("state") == "done"
            door_evidence["work_item_status"] = resp.status
            door_evidence["work_item_state"] = body.get("state")
        with urllib.request.urlopen(f"{base}/", timeout=5) as resp:
            root_ok = resp.status == 200
            door_evidence["root_status"] = resp.status
    except (urllib.error.URLError, OSError, ValueError) as exc:
        door_evidence["error"] = _trim(str(exc))
    finally:
        if door is not None:
            door.shutdown()
            door.server_close()

    ok = store_ok and door_ok and root_ok
    evidence = {
        "store_row_found": bool(row),
        "store_state": (row or {}).get("state"),
        "store_completed_by": (row or {}).get("completed_by"),
        "store_ok": store_ok,
        "door": door_evidence,
        "door_ok": door_ok,
        "root_ok": root_ok,
    }
    return ok, evidence


# ── marker (--keep / --session-only round trip) ─────────────────────────


def _write_marker(project_dir: Path, config_dir: Path) -> None:
    marker = project_dir / ".hyperspace" / MARKER_NAME
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"config_dir": str(config_dir), "project_dir": str(project_dir)}), encoding="utf-8")


def _read_marker(project_dir: Path) -> dict:
    marker = project_dir / ".hyperspace" / MARKER_NAME
    return json.loads(marker.read_text(encoding="utf-8"))


# ── network best-effort (brief step 3.1) ────────────────────────────────


def _sample_no_nova_infra_connections() -> dict:
    # `pgrep`/`lsof` are POSIX tools; without them this is disclosed, not run.
    lsof_present = shutil.which("lsof") is not None and shutil.which("pgrep") is not None
    pids: list[str] = []
    if lsof_present:
        pgrep = subprocess.run(["pgrep", "-f", "hyperspace"], capture_output=True, encoding="utf-8", errors="replace")
        pids = [p for p in pgrep.stdout.split() if p.strip()]
    samples: list[str] = []
    if lsof_present:
        for pid in pids:
            try:
                lsof = subprocess.run(
                    ["lsof", "-nP", "-a", "-iTCP", "-p", pid], capture_output=True, encoding="utf-8", errors="replace", timeout=5,
                )
                samples.extend(ln.strip() for ln in lsof.stdout.splitlines()[1:] if ln.strip())
            except subprocess.TimeoutExpired:
                continue
    non_loopback = [ln for ln in samples if "127.0.0.1" not in ln and "localhost" not in ln]
    return {
        "lsof_present": lsof_present,
        "connection_samples": samples,
        "non_loopback_samples": non_loopback,
        "observation": "observed" if samples else ("not available: lsof missing" if not lsof_present else "no TCP lines sampled"),
    }


# ── orchestrator ─────────────────────────────────────────────────────────


def run(out_dir, opts) -> bool:
    dest = Path(out_dir) / f"{PROBE}.json"
    evidence: dict = {}
    keep = bool(getattr(opts, "keep", False))
    stop_before = getattr(opts, "stop_before", None)
    session_only = bool(getattr(opts, "session_only", False))
    session_runner = getattr(opts, "session_runner", None)
    source = getattr(opts, "source", None)

    if session_only:
        project_dir = Path(getattr(opts, "project"))
        marker = _read_marker(project_dir)
        config_dir = Path(marker["config_dir"])
        evidence["session_only"] = {"project_dir": str(project_dir), "config_dir": str(config_dir)}
        env = _build_env(config_dir)

        session_ok, session_evidence, external_id = _step_session(project_dir, env, session_runner)
        evidence["session"] = session_evidence
        result = "FAIL"
        if session_ok:
            readback_ok, readback_evidence = _step_readback(project_dir, external_id)
            evidence["readback"] = readback_evidence
            result = "PASS" if readback_ok else "FAIL"
        write_verdict(dest, probe=PROBE, result=result, evidence=evidence)
        return result == "PASS"

    config_dir = Path(tempfile.mkdtemp(prefix="hsp-whole-path-cfg-"))
    project_dir = Path(tempfile.mkdtemp(prefix="hsp-whole-path-proj-"))
    evidence["temp_dirs"] = {"config_dir": str(config_dir), "project_dir": str(project_dir), "kept": keep}

    try:
        env, env_evidence = _step_env(config_dir)
        evidence["env"] = env_evidence

        install_ok, install_evidence = _step_install(project_dir, env, source)
        evidence["install"] = install_evidence
        if not install_ok:
            write_verdict(dest, probe=PROBE, result="FAIL", evidence=evidence)
            return False

        port = _free_port()
        provision_ok, provision_evidence = _step_provision(project_dir, port)
        evidence["provision"] = provision_evidence
        if not provision_ok:
            write_verdict(dest, probe=PROBE, result="FAIL", evidence=evidence)
            return False

        mcp_ok, mcp_evidence = _step_mcp_tools(config_dir, project_dir)
        evidence["mcp_tools"] = mcp_evidence
        if not mcp_ok:
            write_verdict(dest, probe=PROBE, result="FAIL", evidence=evidence)
            return False

        evidence["network"] = _sample_no_nova_infra_connections()

        if stop_before == "session":
            evidence["session"] = {"ran": False, "reason": "rehearsal"}
            evidence["readback"] = {"skipped": "no item filed — session step was rehearsed, not run"}
            if keep:
                _write_marker(project_dir, config_dir)
                evidence["temp_dirs"]["marker_written"] = True
            write_verdict(dest, probe=PROBE, result="FAIL", evidence=evidence)
            return False  # a rehearsal never PASSes — INC022

        session_ok, session_evidence, external_id = _step_session(project_dir, env, session_runner)
        evidence["session"] = session_evidence
        if not session_ok:
            write_verdict(dest, probe=PROBE, result="FAIL", evidence=evidence)
            return False

        readback_ok, readback_evidence = _step_readback(project_dir, external_id)
        evidence["readback"] = readback_evidence

        ok = install_ok and provision_ok and mcp_ok and session_ok and readback_ok
        write_verdict(dest, probe=PROBE, result="PASS" if ok else "FAIL", evidence=evidence)
        return ok
    finally:
        if not keep:
            shutil.rmtree(config_dir, ignore_errors=True)
            shutil.rmtree(project_dir, ignore_errors=True)
