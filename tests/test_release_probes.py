"""T5.3 — `probes/probe_whole_path.py` and `probes/probe_consumable.py`.

Covers: (a) `probes/run.py` accepts `whole_path`/`consumable` as probe names
(no longer refused with exit 2); (b) `probe_whole_path.run()` with
`opts.source == "local"` and a FAKE `opts.session_runner` performs the real
install/provision/mcp-tools sequence against a LOCAL marketplace (this repo
root) and reads a real filed-and-closed item back — the fake runner still
performs the loop's real side effects (files, closes) over the same stdio
launcher a real `claude -p` session would use, it just skips spawning
`claude` itself; (c) `opts.stop_before == "session"` records
`session={"ran": false, "reason": "rehearsal"}` and FAILs (a rehearsal never
PASSes — INC022); (d) `probe_consumable.run()` with `opts.source == "local"`
builds the throwaway consumer and records the dependency-resolution attempt.

Every test here needs the real `claude` CLI on PATH (marketplace add/install,
`plugin validate --strict`) — skipped, not failed, when it is absent (this
repo's CI installs `claude` only for its own dedicated steps, after the
`pytest tests/ -q` step; see `.github/workflows/ci.yml`).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

needs_claude = pytest.mark.skipif(shutil.which("claude") is None, reason="`claude` CLI required on PATH")


def _venv_python() -> Path:
    venv_python = ROOT / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


# ── (a) run.py accepts the two new names ────────────────────────────────


@needs_claude
def test_run_py_accepts_whole_path_and_consumable_names(tmp_path):
    out_dir = tmp_path / "probes-out"
    proc = subprocess.run(
        [str(_venv_python()), str(ROOT / "probes" / "run.py"), "--out", str(out_dir),
         "--stop-before", "session", "--source", "local", "whole_path"],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode != 2, proc.stdout + proc.stderr
    assert "unknown probe name" not in proc.stderr
    assert (out_dir / "whole_path.json").is_file()


@needs_claude
def test_run_py_all_still_excludes_the_two_new_probes():
    from probes.run import PROBES, EXTRA_PROBES

    assert "whole_path" not in PROBES
    assert "consumable" not in PROBES
    assert set(EXTRA_PROBES) == {"whole_path", "consumable"}


# ── (c) stop_before session — a rehearsal never PASSes ──────────────────


@needs_claude
def test_probe_whole_path_stop_before_session_fails_by_design(tmp_path):
    from probes import probe_whole_path
    import argparse

    opts = argparse.Namespace(
        source="local", stop_before="session", keep=False, session_only=False,
        project=None, session_runner=None,
    )
    ok = probe_whole_path.run(tmp_path, opts)
    assert ok is False

    payload = json.loads((tmp_path / "whole_path.json").read_text())
    assert payload["result"] == "FAIL"
    assert payload["evidence"]["session"] == {"ran": False, "reason": "rehearsal"}
    # every earlier step is recorded as having run (and passed) — install,
    # provision, mcp_tools — not silently skipped alongside the session.
    assert payload["evidence"]["install"]["marketplace_add"]["exit_code"] == 0
    assert payload["evidence"]["provision"]["env_dir_ok"] is True
    assert payload["evidence"]["mcp_tools"]["missing_required"] == []


# ── (b) a FAKE session runner performs the real side effects ────────────


async def _fake_session_side_effects(project_dir: Path, config_dir: Path) -> tuple[str, str]:
    """Stands in for a real `claude -p` session: talks to the SAME installed
    launcher a real session would (`hyperspace`'s `.mcp.json` entry), filing
    and closing one real work item — so the probe's step 6 readback has a
    real row to find, exactly as a genuine session would have left one."""
    from mcp import StdioServerParameters
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    from probes.probe_whole_path import _find_installed_launcher

    launcher = _find_installed_launcher(config_dir)
    assert launcher is not None, "installed launcher not found under the fake config dir"

    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    params = StdioServerParameters(command="sh", args=[str(launcher)], env=env)

    ext = "whole-path-test:add-hello"
    candidate = {
        "project": "whole-path-test", "external_id": ext, "name": "Add hello.txt",
        "type": "task", "state": "ready", "parent_work_item": None,
        "assignee_agent": None, "team": None, "idempotency_key": f"{ext}-create",
        "specification": {
            "problem": "hello.txt does not exist yet in this fresh probe project directory.",
            "why_it_matters": "The whole-path probe's fake session step needs a real filed and "
                              "closed row for step 6's readback to find, exactly as a genuine "
                              "claude -p session would have left one.",
            "context_pointer": "tests/test_release_probes.py",
        },
        "source_references": [{"uri": "tests/test_release_probes.py"}],
        "effort_level": "quick", "module": None,
        "acceptance_criteria": [{
            "statement": "hello.txt exists.",
            "verification": {"kind": "file_state", "path": "hello.txt", "assertion": "exists"},
        }],
        "proposer_identity": "probe-test", "proposer_surface": "cli-mac",
        "uncertainty_notes": [],
    }

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            setup = await session.call_tool(
                "upsert_project", {"code": "whole-path-test", "name": "Whole-path probe fixture"},
            )
            assert not setup.is_error, setup.content[0].text

            filed = await session.call_tool("upsert_work_item", candidate)
            assert not filed.is_error, filed.content[0].text
            filing_id = json.loads(filed.content[0].text)["filing_id"]

            (project_dir / "hello.txt").write_text("hello", encoding="utf-8")

            closed = await session.call_tool("complete_workitem", {
                "project": "whole-path-test", "external_id": ext,
                "touched": [{"path": "hello.txt", "effect": "created"}],
                "idempotency_key": f"{ext}-done",
                "proposer_identity": "probe-test", "proposer_surface": "cli-mac",
            })
            assert not closed.is_error, closed.content[0].text
            outcome = json.loads(closed.content[0].text)
            assert outcome.get("outcome") == "done", outcome

    return ext, filing_id


def _make_fake_runner():
    def fake_runner(prompt, *, cwd, env, timeout):
        config_dir = Path(env["CLAUDE_CONFIG_DIR"])
        ext, run_id = asyncio.run(_fake_session_side_effects(Path(cwd), config_dir))
        stdout = json.dumps({"result": f"Filed and closed.\nexternal_id={ext} run_id={run_id}"})
        return subprocess.CompletedProcess(args=["fake-session-runner"], returncode=0, stdout=stdout, stderr="")

    return fake_runner


@needs_claude
def test_probe_whole_path_with_fake_session_runner_passes(tmp_path):
    from probes import probe_whole_path
    import argparse

    opts = argparse.Namespace(
        source="local", stop_before=None, keep=False, session_only=False,
        project=None, session_runner=_make_fake_runner(),
    )
    ok = probe_whole_path.run(tmp_path, opts)

    payload = json.loads((tmp_path / "whole_path.json").read_text())
    assert ok is True, payload["evidence"]
    assert payload["result"] == "PASS"
    assert payload["evidence"]["session"]["ran"] is True
    assert payload["evidence"]["session"]["external_id"] == "whole-path-test:add-hello"
    assert payload["evidence"]["readback"]["store_state"] == "done"
    assert payload["evidence"]["readback"]["store_completed_by"] == "hyperspace-verifier"
    assert payload["evidence"]["readback"]["door_ok"] is True


# ── --session-only (standalone-terminal resume, register A19) ───────────


@needs_claude
def test_probe_whole_path_session_only_resumes_a_kept_rehearsal(tmp_path):
    """The standalone-terminal path this row's dispatch calls for: a
    `--keep`'d rehearsal (steps 1-4, `--stop-before session`) leaves a marker
    behind; `--session-only --project <that dir>` reads it back and runs only
    the session + readback steps — the shape a plain terminal outside any
    Claude Code session would use to actually run `claude -p` (A19)."""
    from probes import probe_whole_path
    import argparse

    rehearsal_opts = argparse.Namespace(
        source="local", stop_before="session", keep=True, session_only=False,
        project=None, session_runner=None,
    )
    rehearsal_ok = probe_whole_path.run(tmp_path, rehearsal_opts)
    assert rehearsal_ok is False  # a rehearsal never PASSes — INC022

    rehearsal_payload = json.loads((tmp_path / "whole_path.json").read_text())
    project_dir = rehearsal_payload["evidence"]["temp_dirs"]["project_dir"]
    config_dir = rehearsal_payload["evidence"]["temp_dirs"]["config_dir"]
    assert rehearsal_payload["evidence"]["temp_dirs"]["marker_written"] is True

    try:
        session_only_opts = argparse.Namespace(
            source="local", stop_before=None, keep=False, session_only=True,
            project=project_dir, session_runner=_make_fake_runner(),
        )
        ok = probe_whole_path.run(tmp_path, session_only_opts)

        payload = json.loads((tmp_path / "whole_path.json").read_text())
        assert ok is True, payload["evidence"]
        assert payload["result"] == "PASS"
        assert payload["evidence"]["session_only"]["project_dir"] == project_dir
        assert payload["evidence"]["session_only"]["config_dir"] == config_dir
        assert payload["evidence"]["readback"]["store_state"] == "done"
    finally:
        shutil.rmtree(project_dir, ignore_errors=True)
        shutil.rmtree(config_dir, ignore_errors=True)


# ── (d) probe_consumable local dependency-resolution attempt ────────────


@needs_claude
def test_probe_consumable_local_records_dependency_attempt(tmp_path):
    from probes import probe_consumable
    import argparse

    opts = argparse.Namespace(source="local")
    ok = probe_consumable.run(tmp_path, opts)

    payload = json.loads((tmp_path / "consumable.json").read_text())
    # tag is never present in a local rehearsal (no release cut yet) — FAIL
    # by design, same INC022 discipline as whole_path's --stop-before session.
    assert payload["evidence"]["tag"]["present"] is False
    assert "rehearsal" in payload["evidence"]["tag"]["reason"]
    # the consumer/dependency attempt is recorded verbatim either way —
    # this repo's own empirical read is that it does NOT resolve against a
    # bare local directory marketplace (register A5a: git-tag resolution).
    consumer_evidence = payload["evidence"]["consumer"]
    assert "dependency_resolved" in consumer_evidence
    assert consumer_evidence["install_consumer"]["exit_code"] == 0
    assert ok is False
