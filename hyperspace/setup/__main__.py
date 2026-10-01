"""`python -m hyperspace.setup` — the bootstrap entrypoint that runs BEFORE
`.hyperspace/env` exists, when the plugin's PyPI dependencies (pydantic, etc.)
are not installed anywhere yet. The setup skill reaches it through
`bin/hyperspace_setup.py`, which puts the plugin root on `sys.path` itself so
the command needs no `PYTHONPATH=` prefix (sh-only syntax) on any OS.

`hyperspace.cli` (and everything it imports — `hyperspace.http`,
`hyperspace.tools`, `hyperspace.contracts`) needs those dependencies at
IMPORT time, so `python3 -m hyperspace.cli` cannot be the first command run
against a bare interpreter (found empirically, not assumed — see the
import-chain note atop `provision.py`). This module's own import chain is
`hyperspace` (version constant only), `hyperspace.config` (stdlib
`tomllib`), `hyperspace.store` (stdlib `sqlite3`), and `hyperspace.setup.provision`
(stdlib only, by the same note) — nothing else, so it runs on whatever
`python3` the skill's step 1 just checked.

Mirrors `hyperspace init [--provision ...]`'s flags exactly (same store-init
step, same `provision_and_report` call) so the two commands read as one
familiar shape to whoever runs them, even though only this one is safe to
run before the environment exists.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .._pyfloor import require_python

require_python()

from .._stdio import utf8_stdio  # noqa: E402
from ..config import JUDGES  # noqa: E402
from ..store import Store  # noqa: E402
from .provision import provision_and_report  # noqa: E402


def main(argv: list[str] | None = None, prog: str = "python -m hyperspace.setup") -> int:
    utf8_stdio()
    argv = sys.argv[1:] if argv is None else list(argv)

    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("--dir", default=".")
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--judge", default=None, choices=list(JUDGES))
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--user", default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    project_dir = Path(args.dir).resolve()
    db_path = project_dir / ".hyperspace" / "graph.db"
    already_existed = db_path.exists()
    store = Store.init(db_path)
    store.close()
    print(f"{'already initialised' if already_existed else 'initialised'} {db_path}")

    if args.provision:
        return provision_and_report(project_dir, judge=args.judge, port=args.port, user=args.user)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
