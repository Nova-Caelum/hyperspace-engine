"""hyperspace/mcp/server.py — the stdio MCP server Claude Code spawns per
session (row T4.1).

Lists the verifier's `complete_workitem` plus every tool in
`hyperspace.tools.registry.TOOLS`, answers each against the local store, and
lazily starts (or adopts) the loopback door on the first tool call — never
at import time, so `tools/list` still answers when `.hyperspace/graph.db` is
missing (Claude Code must still see the server as connected).

# NOTE: the postponed-evaluation-of-annotations future-import is intentionally
# absent from this module — the canonical stdio server
# (`reference/verifier_server.py`) carries the same constraint for its
# higher-level `MCPServer`; kept here too even though the low-level `Server`
# below is built from a pre-constructed `mcp.types.Tool` list rather than
# typed function signatures, so real annotations were not strictly required
# for THIS approach — the brief's instruction is followed regardless.

Built against the `mcp` Python SDK (installed: 2.2.0), API confirmed via
context7 (`/websites/py_sdk_modelcontextprotocol_io_v2`) against this
repo's actual installed package (not assumed from docs alone — B2):

  from mcp.server import Server, ServerRequestContext, NotificationOptions
  from mcp.server.stdio import stdio_server
  import mcp.types as types

  types.Tool(name=..., description=..., input_schema={...})   # -> aliases to
      # `inputSchema` on the wire; a pre-built JSON-schema dict is accepted
      # directly — no typed-function-signature requirement, so the brief's
      # escalation ("cannot declare a tool from a pre-built JSON schema") does
      # not apply here.

  server = Server("hyperspace", on_list_tools=..., on_call_tool=...)
  async with stdio_server() as (read_stream, write_stream):
      await server.run(read_stream, write_stream,
                        server.create_initialization_options(
                            notification_options=NotificationOptions(tools_changed=True)))

The judge is selected from the project's `.hyperspace/config.toml` through
`hyperspace.judge.get_judge(load_config(root))`, so the MCP path honours the
user's configured runner (`none` when nothing is configured).
"""
import json
import os
import sys
import threading
import tomllib
from pathlib import Path

from pydantic import ValidationError

from mcp.server import NotificationOptions, Server, ServerRequestContext
import mcp.types as types

from ..http.server import is_bound, start
from ..config import load_config
from ..judge import get_judge
from ..store import Store
from ..tools.registry import TOOLS, call_tool
from ..verify import CompletionClaim, complete_workitem, local_deps

_DEFAULT_PORT = 8791

# ── the tool table, built once at import time (never touches the store) ────


def _build_tool_list() -> list[types.Tool]:
    tools = [
        types.Tool(
            name="complete_workitem",
            description=(
                "Close a Task Graph row as done by independent verification, synchronously. "
                "The touched list (paths this work created, modified or deleted) IS the "
                "statement of work — no narrative field exists. Returns exactly one of "
                "done | refused | unverifiable | already_done."
            ),
            input_schema=CompletionClaim.model_json_schema(),
        )
    ]
    tools.extend(
        types.Tool(name=spec.name, description=spec.description, input_schema=spec.input_schema)
        for spec in TOOLS.values()
    )
    return tools


_TOOL_LIST = _build_tool_list()

# ── lazy door start — attempted at most once per process, on the first
#    tools/call (never at import time, never blocking tools/list) ──────────

_door_lock = threading.Lock()
_door_attempted = False


def _ensure_door(db_path: Path, port: int) -> None:
    global _door_attempted
    with _door_lock:
        if _door_attempted:
            return
        _door_attempted = True
    try:
        if not is_bound(port):
            start(db_path, port, open_browser=False)
    except Exception as exc:  # noqa: BLE001 — never fail the tool call over the door
        sys.stderr.write(f"hyperspace-mcp: loopback door did not start on port {port}: {exc}\n")


def _read_port(hyperspace_dir: Path) -> int:
    config_path = hyperspace_dir / "config.toml"
    if not config_path.is_file():
        return _DEFAULT_PORT
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return _DEFAULT_PORT
    return int(data.get("port", _DEFAULT_PORT))


def _project_root() -> Path:
    """`CLAUDE_PROJECT_DIR` else cwd (Decisions locked, brief) — re-resolved on
    every call rather than cached at import time."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


# ── result helpers ───────────────────────────────────────────────────────────


def _ok(payload) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload))])


def _err(message: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=message)], is_error=True)


def _is_tool_error_payload(payload) -> bool:
    """`hyperspace.tools.registry.call_tool` never raises — a `ToolError` (or
    any other exception) comes back as `{"error": {"code", "message"}}`. This
    detects that shape so it can be surfaced as `isError: true` instead of
    being handed back to the client as a normal (successful) result."""
    return (
        isinstance(payload, dict)
        and set(payload.keys()) == {"error"}
        and isinstance(payload.get("error"), dict)
        and {"code", "message"} <= payload["error"].keys()
    )


def _judge_for(root: Path):
    """The configured judge for this project — `none` unless config says otherwise."""
    return get_judge(load_config(root))


async def _call_complete_workitem(store: Store, root: Path, arguments: dict) -> dict:
    claim = CompletionClaim(**arguments)  # ValidationError propagates to the caller
    deps = local_deps(store, _judge_for(root), project_root=root)
    return await complete_workitem(claim, deps)


# ── the two protocol handlers ────────────────────────────────────────────────


async def _on_list_tools(ctx: ServerRequestContext, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=_TOOL_LIST)


async def _on_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    name = params.name
    arguments = dict(params.arguments or {})

    root = _project_root()
    hyperspace_dir = root / ".hyperspace"
    db_path = hyperspace_dir / "graph.db"
    if not db_path.is_file():
        return _err(f"no store at {db_path} — run `hyperspace init` first")

    _ensure_door(db_path, _read_port(hyperspace_dir))

    try:
        store = Store.open(db_path)
    except Exception as exc:  # noqa: BLE001 — never a crash (brief step 3)
        return _err(f"{type(exc).__name__}: {exc}")

    try:
        if name == "complete_workitem":
            payload = await _call_complete_workitem(store, root, arguments)
        elif name in TOOLS:
            payload = call_tool(store, name, arguments)
        else:
            return _err(f"no such tool: {name!r}")
    except ValidationError as exc:
        return _err(str(exc))
    except Exception as exc:  # noqa: BLE001 — everything else: class + message, never a crash
        return _err(f"{type(exc).__name__}: {exc}")
    finally:
        store.close()

    if _is_tool_error_payload(payload):
        return _err(payload["error"]["message"])
    return _ok(payload)


# ── construction / entrypoint ───────────────────────────────────────────────


def build_server() -> Server:
    return Server("hyperspace", on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)


def main() -> None:
    import anyio
    from mcp.server.stdio import stdio_server

    server = build_server()

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(notification_options=NotificationOptions(tools_changed=True)),
            )

    anyio.run(_run)
