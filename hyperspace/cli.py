"""Hyperspace Engine CLI entrypoint.

A subcommand registry (name -> callable) that later rows extend by adding
one entry each. No subcommand bodies live here — the store row adds `init`,
the door row adds `serve`, the setup row adds `doctor`.
"""
import argparse
import sys
from pathlib import Path

from hyperspace import __version__
from hyperspace.store import Store


def _cmd_init(args: argparse.Namespace) -> int:
    """`hyperspace init [--dir <project-dir>]` — creates `<dir>/.hyperspace/graph.db`."""
    sub_parser = argparse.ArgumentParser(prog="hyperspace init", add_help=False)
    sub_parser.add_argument("--dir", default=".")
    sub_args = sub_parser.parse_args(args.rest)

    db_path = Path(sub_args.dir).resolve() / ".hyperspace" / "graph.db"
    already_existed = db_path.exists()
    store = Store.init(db_path)
    store.close()
    print(f"{'already initialised' if already_existed else 'initialised'} {db_path}")
    return 0


# Subcommand registry: name -> callable(args: argparse.Namespace) -> int.
# Later rows extend this dict by adding one entry each; this row installs `init`.
SUBCOMMANDS: dict = {"init": _cmd_init}

_NO_SUBCOMMANDS_MESSAGE = (
    "no subcommands installed yet — the store row adds `init`, "
    "the door row adds `serve`, the setup row adds `doctor`"
)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)

    parser = argparse.ArgumentParser(prog="hyperspace", add_help=False)
    parser.add_argument("--version", action="store_true")
    parser.add_argument("command", nargs="?", default=None)
    parser.add_argument("rest", nargs=argparse.REMAINDER)

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    if args.version:
        print(__version__)
        return 0

    if args.command is None or args.command not in SUBCOMMANDS:
        print(_NO_SUBCOMMANDS_MESSAGE, file=sys.stderr)
        return 2

    return SUBCOMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
