#!/usr/bin/env python3
"""probes/run.py — the one runner every probe in this suite shares (row T5.2).

Validates the probe names FIRST — an unknown name refuses with exit 2 before
anything (not even `--out`) is created — then imports each `probes.probe_<name>`
module by name and calls its `run(out_dir, opts) -> bool`, which writes its own
verdict via `_verdict.write_verdict`. `all` expands to the ten probes below, in
a fixed order.

Usage: python probes/run.py --out <dir> [--no-paid] [--source <path>] <probe> [<probe>...]
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="probes/run.py")
    parser.add_argument("--out", required=True, help="directory to write <probe>.json verdicts into")
    parser.add_argument("--no-paid", action="store_true", dest="no_paid",
                        help="disable the judge_modes probe's keyed/CLI branches (anthropic, "
                             "openrouter, claude-code, codex) — this build session never makes "
                             "a paid model call or nests a `claude`/`codex` invocation")
    parser.add_argument("--source", default=None,
                        help="local clone (or git URL) the ui_localhost/installer probes may "
                             "reuse for a reproducibility rebuild; omit to use the network default")
    parser.add_argument("probes", nargs="+", help="probe name(s), or 'all' for the full ten")
    args = parser.parse_args(argv)

    names = PROBES if args.probes == ["all"] else args.probes
    unknown = [n for n in names if n not in PROBES]
    if unknown:
        print(
            f"run.py: unknown probe name(s): {', '.join(unknown)} — "
            f"must be one of: {', '.join(PROBES)} (or 'all')",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    opts = argparse.Namespace(no_paid=args.no_paid, source=args.source, out_dir=out_dir)

    all_pass = True
    for name in names:
        module = importlib.import_module(f"probes.probe_{name}")
        ok = bool(module.run(out_dir, opts))
        if not ok:
            all_pass = False
        print(f"{name}: {'PASS' if ok else 'FAIL'} {out_dir / f'{name}.json'}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
