"""Hyperspace Engine CLI entrypoint.

A subcommand registry (name -> callable) that later rows extend by adding
one entry each. No subcommand bodies live here — the store row adds `init`,
the door row adds `serve`, the setup row adds `doctor`.
"""
import argparse
import errno
import sys
import tomllib
import webbrowser
from pathlib import Path

from hyperspace import __version__
from hyperspace.store import Store
from hyperspace.http.server import create_door

_DEFAULT_PORT = 8791


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


def _read_config_port(hyperspace_dir: Path, default: int = _DEFAULT_PORT) -> int:
    """Minimal stdlib `tomllib` read of `<hyperspace_dir>/config.toml`'s `port`
    key — absent file or absent key both fall back to `default`."""
    config_path = hyperspace_dir / "config.toml"
    if not config_path.is_file():
        return default
    with config_path.open("rb") as f:
        data = tomllib.load(f)
    return int(data.get("port", default))


def _prepare_serve(args: argparse.Namespace, opener=webbrowser.open):
    """Resolves `--dir`/config/`--port`, binds the door, and opens the
    browser if asked — everything `hyperspace serve` does before it blocks on
    `serve_forever()`. Split out from `_cmd_serve` so the port-busy and
    `--open` behaviors are directly callable and assertable without blocking
    a test on an indefinite request loop.

    Returns the bound `Door` on success, or an `int` exit code on failure
    (missing db / port already in use).
    """
    sub_parser = argparse.ArgumentParser(prog="hyperspace serve", add_help=False)
    sub_parser.add_argument("--port", type=int, default=None)
    sub_parser.add_argument("--open", action="store_true")
    sub_parser.add_argument("--dir", default=".")
    sub_args = sub_parser.parse_args(args.rest)

    project_dir = Path(sub_args.dir).resolve()
    hyperspace_dir = project_dir / ".hyperspace"
    db_path = hyperspace_dir / "graph.db"
    if not db_path.is_file():
        print(f"no {db_path} — run `hyperspace init` first", file=sys.stderr)
        return 1

    port = sub_args.port if sub_args.port is not None else _read_config_port(hyperspace_dir)

    try:
        door = create_door(db_path, port=port)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                f"port {port} is in use — pass --port <other> or set port in .hyperspace/config.toml",
                file=sys.stderr,
            )
            return 1
        raise

    bound_port = door.server_address[1]
    print(f"hyperspace: serving http://127.0.0.1:{bound_port}/ (Ctrl-C to stop)")
    if sub_args.open:
        opener(f"http://127.0.0.1:{bound_port}/")
    return door


def _cmd_serve(args: argparse.Namespace) -> int:
    """`hyperspace serve [--port N] [--open] [--dir <project-dir>]` — binds
    the loopback door and blocks in the foreground until Ctrl-C."""
    result = _prepare_serve(args)
    if isinstance(result, int):
        return result

    door = result
    try:
        door.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        door.shutdown()
        door.server_close()
    return 0


# Subcommand registry: name -> callable(args: argparse.Namespace) -> int.
# Later rows extend this dict by adding one entry each; this row installs `serve`
# (the store row already installed `init`).
SUBCOMMANDS: dict = {"init": _cmd_init, "serve": _cmd_serve}

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
