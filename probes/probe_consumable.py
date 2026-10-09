#!/usr/bin/env python3
"""probes/probe_consumable.py — T11: the consumability probe.

Three sub-checks, all must PASS for result PASS:
  (i)   `claude plugin validate --strict .` on the repo root — composes
        `probes/check_validate_strict.py`'s own function directly (never
        re-implemented; same DRY precedent every other probe in this suite
        follows for its own check_*.py).
  (ii)  a semver git tag on the released commit. Under `opts.source ==
        "github"`: `git tag --points-at HEAD` plus `git ls-remote --tags
        origin` confirming it is pushed. Otherwise (local rehearsal, no
        release cut yet): recorded honestly as
        `{"present": false, "reason": "rehearsal — the tag is cut by the
        controller on the release owner's go-ahead"}` — FAIL by design, same INC022
        discipline `probe_whole_path.py`'s `--stop-before session` applies.
  (iii) a throwaway consumer plugin — `.claude-plugin/plugin.json` declaring
        `{"name": "hyperspace-engine", "marketplace": "hyperspace-engine",
        "version": "^1.0"}` — installed in a fresh `CLAUDE_CONFIG_DIR` after
        adding both marketplaces, checked via `claude plugin list --json` and
        `claude plugin details`. Recorded verbatim, whatever the outcome:
        this repo's own empirical read (this row, 2026-09-27, `claude`
        2.1.251) is that a plugin dependency does NOT auto-install/resolve
        against a bare LOCAL directory marketplace — `claude plugin list`
        reports the consumer "failed to load" with
        `Dependency "hyperspace-engine@hyperspace-engine" is not installed`
        until hyperspace-engine is installed explicitly — matching this
        row's own anticipated Escalate clause ("dependencies may require a
        git source"); register A5a says resolution is by marketplace +
        semver against git TAGS, which a raw local directory has none of.
        This sub-check is therefore expected to legitimately FAIL under
        `--source local`; the `--source github` run in the test session,
        against a real tagged release, is what actually settles T11 — this
        probe does not restructure the marketplace to force a local PASS.

Usage: imported by probes/run.py; PROBE = "consumable"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verdict import write_verdict  # noqa: E402
from check_validate_strict import check_validate_strict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROBE = "consumable"

GITHUB_SOURCE = "Nova-Caelum/hyperspace-engine"
ENGINE_MARKETPLACE = "hyperspace-engine"
ENGINE_PLUGIN_ID = "hyperspace-engine@hyperspace-engine"
CONSUMER_MARKETPLACE = "throwaway-consumer-mkt"
CONSUMER_PLUGIN_ID = f"throwaway-consumer@{CONSUMER_MARKETPLACE}"

REQUIRED_ENGINE_SKILL = "gear2-understand"


def _trim(text, limit: int = 4000):
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _resolve_source(source: str | None) -> str:
    if source in (None, "local"):
        return str(ROOT)
    if source == "github":
        return GITHUB_SOURCE
    return source


# ── (ii) tag ─────────────────────────────────────────────────────────────


def _check_tag(source: str | None) -> tuple[bool, dict]:
    points_at = subprocess.run(
        ["git", "tag", "--points-at", "HEAD"], cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
    )
    tags = [t for t in points_at.stdout.splitlines() if t.strip()]
    # Claude Code resolves a versioned dependency against `{plugin}--v<semver>`
    # tags (the `claude plugin tag` convention); a bare `v<semver>` is not read.
    semver_tags = [t for t in tags if t.strip().startswith("hyperspace-engine--v")]

    if source != "github":
        return False, {
            "present": False,
            "reason": "rehearsal — the tag is cut by the controller on the release owner's go-ahead",
            "points_at_head": tags,
        }

    if not semver_tags:
        return False, {"present": False, "points_at_head": tags, "reason": "no hyperspace-engine--v<semver> tag on HEAD (claude plugin tag convention)"}

    ls_remote = subprocess.run(
        ["git", "ls-remote", "--tags", "origin"], cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
    )
    pushed = any(f"refs/tags/{semver_tags[0]}" in line for line in ls_remote.stdout.splitlines())
    return bool(pushed), {
        "present": True, "tag": semver_tags[0], "points_at_head": tags,
        "pushed_to_origin": pushed,
        "ls_remote_tags": {"command": "git ls-remote --tags origin", "exit_code": ls_remote.returncode,
                            "stdout": _trim(ls_remote.stdout)},
    }


# ── (iii) throwaway consumer ─────────────────────────────────────────────


def _write_consumer_plugin(consumer_dir: Path) -> None:
    plugin_dir = consumer_dir / ".claude-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "marketplace.json").write_text(json.dumps({
        "name": CONSUMER_MARKETPLACE,
        "owner": {"name": "Nova Caelum (throwaway probe fixture)"},
        # a dependency in another marketplace is blocked unless the root marketplace allows it
        "allowCrossMarketplaceDependenciesOn": [ENGINE_MARKETPLACE],
        "plugins": [
            {"name": "throwaway-consumer", "source": "./", "description": "throwaway consumability probe fixture"}
        ],
    }), encoding="utf-8")
    (plugin_dir / "plugin.json").write_text(json.dumps({
        "name": "throwaway-consumer",
        "version": "0.0.1",
        "description": "throwaway consumability probe fixture — never committed, never published",
        "dependencies": [
            {"name": "hyperspace-engine", "marketplace": ENGINE_MARKETPLACE, "version": "^1.0"}
        ],
    }), encoding="utf-8")


def _run_claude(args: list[str], *, cwd: Path, env: dict, timeout: int = 120) -> dict:
    claude = shutil.which("claude")
    if claude is None:
        return {"command": "claude " + " ".join(args), "error": "`claude` not found on PATH"}
    proc = subprocess.run([claude, *args], cwd=cwd, env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    return {
        "command": "claude " + " ".join(args),
        "exit_code": proc.returncode,
        "stdout": _trim(proc.stdout),
        "stderr": _trim(proc.stderr),
    }


def _check_consumer(source: str | None) -> tuple[bool, dict]:
    import os

    engine_source = _resolve_source(source)

    with tempfile.TemporaryDirectory(prefix="hsp-consumable-cfg-") as cfg_str, \
         tempfile.TemporaryDirectory(prefix="hsp-consumable-consumer-") as consumer_str, \
         tempfile.TemporaryDirectory(prefix="hsp-consumable-proj-") as proj_str:
        cfg, consumer_dir, project_dir = Path(cfg_str), Path(consumer_str), Path(proj_str)
        _write_consumer_plugin(consumer_dir)

        env = {**os.environ, "CLAUDE_CONFIG_DIR": str(cfg)}

        add_engine = _run_claude(["plugin", "marketplace", "add", engine_source], cwd=project_dir, env=env)
        add_consumer = _run_claude(["plugin", "marketplace", "add", str(consumer_dir)], cwd=project_dir, env=env)
        install_consumer = _run_claude(
            ["plugin", "install", CONSUMER_PLUGIN_ID, "--scope", "project"], cwd=project_dir, env=env,
        )
        plugin_list = _run_claude(["plugin", "list", "--json"], cwd=project_dir, env=env)
        engine_details = _run_claude(["plugin", "details", ENGINE_MARKETPLACE], cwd=project_dir, env=env)
        consumer_details = _run_claude(["plugin", "details", "throwaway-consumer"], cwd=project_dir, env=env)

        try:
            listed = json.loads(plugin_list.get("stdout") or "[]")
        except json.JSONDecodeError:
            listed = None

        consumer_entry = next((p for p in listed if p.get("id") == CONSUMER_PLUGIN_ID), None) if listed else None
        engine_entry = next((p for p in listed if p.get("id") == ENGINE_PLUGIN_ID), None) if listed else None
        # `enabled` alone is the settings.json toggle, not "loaded without
        # error" — `claude plugin list --json` puts an unresolved dependency's
        # failure in a sibling `errors` array while `enabled` stays true
        # (empirically found this row, 2026-09-27: a bare-local-marketplace
        # dependency reads `enabled: true, errors: ["Dependency … is not
        # installed …"]`). Both must hold for "actually loaded".
        consumer_enabled = bool(
            consumer_entry and consumer_entry.get("enabled") and not consumer_entry.get("errors")
        )
        engine_enabled = bool(engine_entry and engine_entry.get("enabled") and not engine_entry.get("errors"))
        gear_listed = REQUIRED_ENGINE_SKILL in (engine_details.get("stdout") or "")

        dependency_resolved = consumer_enabled and engine_enabled and gear_listed

        evidence = {
            "engine_source": engine_source,
            "marketplace_add_engine": add_engine,
            "marketplace_add_consumer": add_consumer,
            "install_consumer": install_consumer,
            "plugin_list_json": plugin_list,
            "plugin_details_engine": engine_details,
            "plugin_details_consumer": consumer_details,
            "consumer_entry": consumer_entry,
            "engine_entry": engine_entry,
            "consumer_enabled": consumer_enabled,
            "engine_enabled": engine_enabled,
            "gear2_understand_listed": gear_listed,
            "dependency_resolved": dependency_resolved,
        }
        return dependency_resolved, evidence


# ── orchestrator ─────────────────────────────────────────────────────────


def run(out_dir, opts) -> bool:
    source = getattr(opts, "source", None)
    evidence: dict = {}

    validate_evidence: dict = {}
    validate_ok = check_validate_strict(validate_evidence)
    evidence["validate_strict"] = validate_evidence

    tag_ok, tag_evidence = _check_tag(source)
    evidence["tag"] = tag_evidence

    consumer_ok, consumer_evidence = _check_consumer(source)
    evidence["consumer"] = consumer_evidence

    ok = validate_ok and tag_ok and consumer_ok
    write_verdict(Path(out_dir) / f"{PROBE}.json", probe=PROBE, result="PASS" if ok else "FAIL", evidence=evidence)
    return ok
