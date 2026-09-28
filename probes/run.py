#!/usr/bin/env python3
"""probes/run.py — the one runner every probe in this suite shares (rows
T5.2, T5.3).

Validates the probe names FIRST — an unknown name refuses with exit 2 before
anything (not even `--out`) is created — then imports each `probes.probe_<name>`
module by name and calls its `run(out_dir, opts) -> bool`, which writes its own
verdict via `_verdict.write_verdict`. `all` expands to the ten scan/regression
probes in `PROBES`, in a fixed order — `whole_path` and `consumable`
(`EXTRA_PROBES`) are accepted names too, but deliberately NEVER included in
`all`: they need `--source`, take real network/subprocess time, and (unlike
the ten) are never part of the no-paid CI subset.

Usage: python probes/run.py --out <dir> [--no-paid] [--source local|github|<path>]
       [--stop-before session] [--keep] [--session-only --project <dir>]
       <probe> [<probe>...]
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROBES = [
    "no_nova_infra", "store_contract", "ui_localhost", "mcp_tools",
    "judge_modes", "pydantic_graph", "installer", "no_vault_refs",
    "gear_names", "known_defects",
]
# T5.3's two probes plus v0.1.3's `claude_runtime` — accepted names, never
# part of `all` (see module docstring): each needs the `claude` CLI on PATH.
EXTRA_PROBES = ["whole_path", "consumable", "claude_runtime"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="probes/run.py")
    parser.add_argument("--out", required=True, help="directory to write <probe>.json verdicts into")
    parser.add_argument("--no-paid", action="store_true", dest="no_paid",
                        help="disable the judge_modes probe's keyed/CLI branches (anthropic, "
                             "openrouter, claude-code, codex) — this build session never makes "
                             "a paid model call or nests a `claude`/`codex` invocation")
    parser.add_argument("--source", default=None,
                        help="local clone (or git URL) the ui_localhost/installer probes may "
                             "reuse for a reproducibility rebuild; for whole_path/consumable, "
                             "'local' (marketplace add <repo root>) or 'github' "
                             "(Nova-Caelum/hyperspace-engine) — omit to use the network default")
    parser.add_argument("--stop-before", default=None, choices=["session"], dest="stop_before",
                        help="whole_path only: rehearse everything up to (not including) the "
                             "claude -p session step; the probe then records "
                             "session={ran:false, reason:'rehearsal'} and FAILs by design "
                             "(a rehearsal never PASSes — INC022)")
    parser.add_argument("--keep", action="store_true",
                        help="keep the temp CLAUDE_CONFIG_DIR/project dirs whole_path/consumable "
                             "create, and (whole_path) write a marker file under the kept "
                             "project's .hyperspace/ so --session-only can resume from it")
    parser.add_argument("--session-only", action="store_true", dest="session_only",
                        help="whole_path only: skip straight to the session + readback steps, "
                             "reusing a --project dir kept from an earlier --keep rehearsal — "
                             "run this from a plain terminal, never nested inside a Claude Code "
                             "session (register A19)")
    parser.add_argument("--project", default=None,
                        help="whole_path --session-only: the kept rehearsal's project dir")
    parser.add_argument("probes", nargs="+", help="probe name(s), or 'all' for the ten scan/regression probes")
    args = parser.parse_args(argv)

    known = PROBES + EXTRA_PROBES
    names = PROBES if args.probes == ["all"] else args.probes
    unknown = [n for n in names if n not in known]
    if unknown:
        print(
            f"run.py: unknown probe name(s): {', '.join(unknown)} — "
            f"must be one of: {', '.join(known)} (or 'all', which expands to the ten "
            f"scan/regression probes only)",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    opts = argparse.Namespace(
        no_paid=args.no_paid,
        source=args.source,
        out_dir=out_dir,
        stop_before=args.stop_before,
        keep=args.keep,
        session_only=args.session_only,
        project=args.project,
        session_runner=None,  # CLI never sets this — only a direct Python call (tests) does
    )

    all_pass = True
    for name in names:
        module = importlib.import_module(f"probes.probe_{name}")
        try:
            ok = bool(module.run(out_dir, opts))
        except Exception as exc:  # noqa: BLE001 — one crashing probe must not silence the rest
            from probes._verdict import write_verdict

            write_verdict(out_dir / f"{name}.json", probe=name, result="FAIL",
                          evidence={"crashed": f"{type(exc).__name__}: {exc}"})
            ok = False
        if not ok:
            all_pass = False
        print(f"{name}: {'PASS' if ok else 'FAIL'} {out_dir / f'{name}.json'}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
