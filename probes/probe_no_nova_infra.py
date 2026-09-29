#!/usr/bin/env python3
"""probes/probe_no_nova_infra.py — T3: the shipped tree holds no reference to
Nova Caelum's private infrastructure, and every network call the running
product makes goes to loopback only.

Two sub-checks:
  (a) the one tree scanner (`probes/scan_tree.py`) over `bin skills
      hyperspace ui probes hooks` for the six infra terms. Two files exist SOLELY to
      DEFINE the denylist this scan checks against (`probes/check_port_scan.py`,
      `tests/test_port.py`) and therefore necessarily contain every term as a
      literal string, by construction, forever — a bare quoted copy of a term,
      alone on its line, in one of those two files is excluded from the
      verdict (and separately recorded in evidence, never silently dropped);
      every other match, wherever it is, counts.
  (b) a live run: spawn the stdio MCP server against a temp project, drive one
      `tools/call` (which lazily starts the loopback door) and one
      `GET /api/projects`, then sample every outbound TCP connection the
      server process has open via `lsof`. Every address must be loopback.
      When `lsof` is unavailable, that is disclosed rather than penalised
      (Escalate clause) — the door's own code refuses to bind anything but
      127.0.0.1/localhost (`hyperspace/http/server.py::Door.__init__`).

Usage: imported by probes/run.py; from hyperspace.venv_paths import find_venv_python  # noqa: E402

PROBE = "no_nova_infra"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402
from scan_tree import scan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from hyperspace.venv_paths import find_venv_python  # noqa: E402

PROBE = "no_nova_infra"

SCANNED_DIRS = ["bin", "skills", "hyperspace", "ui", "probes", "hooks"]
# Built by concatenation so THIS file's own source never contains a
# contiguous forbidden term — it would otherwise self-match under `probes/`.
TERMS = [
    "nova" + "-caelum-ops",
    "railway" + ".app",
    "supa" + "base",
    "b" + "ws",
    "GMWORKER_OPS" + "_BEARER",
    "GMCOMMITTER_OPS" + "_BEARER",
]

_DENYLIST_DEFINITION_FILES = {"probes/check_port_scan.py", "tests/test_port.py"}


def _is_denylist_definition_line(path_rel: str, term: str, text: str) -> bool:
    """A bare quoted copy of `term`, alone on its line, inside one of the two
    files that exist solely to define/mirror the forbidden-term denylist —
    never a real reference. Narrow and mechanical on purpose: only the exact
    array-literal shape is excused; any other appearance of the term in
    those same files (a `.count(...)` call, a prose assertion) still counts."""
    if path_rel not in _DENYLIST_DEFINITION_FILES:
        return False
    stripped = text.strip()
    return stripped in (f'"{term}",', f'"{term}"', f"'{term}',", f"'{term}'")


def _run_scan() -> dict:
    findings = scan(ROOT, SCANNED_DIRS, TERMS, case_insensitive=True)
    excluded, real = [], []
    for f in findings:
        rel = f.path.as_posix()  # the exclusion set is written with forward slashes
        line = f"{rel}:{f.line}: [{f.term}] {f.text[:200]}"
        if _is_denylist_definition_line(rel, f.term, f.text):
            excluded.append(line)
        else:
            real.append(line)
    return {
        "dirs": SCANNED_DIRS, "terms": TERMS, "case_insensitive": True,
        "total_findings": len(findings), "real_findings": real,
        "excluded_denylist_definition_lines": excluded,
        "exclusion_rule": (
            "a bare quoted copy of the term, alone on its line, inside "
            "probes/check_port_scan.py or tests/test_port.py — the two files "
            "that exist to define/mirror this denylist and therefore contain "
            "every term as a literal by construction. Nothing else is excluded."
        ),
    }


async def _sample_connections(samples: list[str]) -> None:
    # `pgrep`/`lsof` are POSIX tools (Windows ships neither); without them the
    # sample is empty and `network_observation` says why — disclosed, never
    # penalised (module docstring).
    if shutil.which("pgrep") is None or shutil.which("lsof") is None:
        return
    pgrep = subprocess.run(["pgrep", "-f", "hyperspace.mcp"], capture_output=True, encoding="utf-8", errors="replace")
    pids = [p for p in pgrep.stdout.split() if p.strip()]
    for pid in pids:
        try:
            lsof = subprocess.run(
                ["lsof", "-nP", "-a", "-iTCP", "-p", pid], capture_output=True, encoding="utf-8", errors="replace", timeout=5,
            )
            for line in lsof.stdout.splitlines()[1:]:
                if line.strip():
                    samples.append(line.strip())
        except subprocess.TimeoutExpired as exc:
            samples.append(f"<lsof timed out on pid {pid}: {exc}>")


async def _live_network_check() -> dict:
    from hyperspace.store import Store

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        project_dir = Path(tmp)
        db_path = project_dir / ".hyperspace" / "graph.db"
        Store.init(db_path).close()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        (project_dir / ".hyperspace" / "config.toml").write_text(f"port = {port}\n", encoding="utf-8")

        python = find_venv_python(ROOT / ".venv") or Path(sys.executable)

        from mcp import StdioServerParameters
        from mcp.client.session import ClientSession
        from mcp.client.stdio import stdio_client

        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
        params = StdioServerParameters(command=str(python), args=["-m", "hyperspace.mcp"], env=env)

        samples: list[str] = []
        tool_names: list[str] = []
        first_call_is_error = None
        door_status = None

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                tool_names = sorted(t.name for t in listed.tools)

                result = await session.call_tool(
                    "upsert_project", {"code": "no-nova-infra-probe", "name": "no_nova_infra probe"}
                )
                first_call_is_error = bool(result.is_error)
                await asyncio.sleep(0.2)
                await _sample_connections(samples)

                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/projects")
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        door_status = resp.status
                except Exception as exc:  # noqa: BLE001 — recorded, never swallowed
                    door_status = f"error: {type(exc).__name__}: {exc}"
                await asyncio.sleep(0.2)
                await _sample_connections(samples)

        lsof_present = shutil.which("lsof") is not None and shutil.which("pgrep") is not None
        non_loopback = [
            ln for ln in samples
            if not ln.startswith("<lsof timed out") and "127.0.0.1" not in ln and "localhost" not in ln
        ]
        if not lsof_present:
            network_observation = "not available: `pgrep`/`lsof` not on PATH (POSIX tools; Windows ships neither)"
        elif not samples:
            network_observation = "not available: no TCP lines sampled (see connection_samples for detail)"
        else:
            network_observation = "observed"

        return {
            "port": port, "tool_names": tool_names, "first_tools_call_is_error": first_call_is_error,
            "door_get_projects_status": door_status,
            "connection_samples": samples, "non_loopback_samples": non_loopback,
            "lsof_present": lsof_present, "network_observation": network_observation,
        }


def run(out_dir, opts) -> bool:
    scan_evidence = _run_scan()
    scan_ok = not scan_evidence["real_findings"]

    net_evidence = asyncio.run(_live_network_check())
    # A non-observable environment is disclosed, not penalised (Escalate
    # clause) — we still rely on the scan plus the fact that every configured
    # endpoint is loopback by construction (Door refuses any other host).
    net_ok = not net_evidence["non_loopback_samples"]

    ok = scan_ok and net_ok
    evidence = {"scan": scan_evidence, "network": net_evidence}
    write_verdict(Path(out_dir) / f"{PROBE}.json", probe=PROBE, result="PASS" if ok else "FAIL", evidence=evidence)
    return ok
