"""hyperspace/http/ — the loopback web door (row T4.2).

Two socket-free modules (`routes.py`) hold the actual contract logic —
`route_get` for the console's REST reads and `route_mcp` for its JSON-RPC
`tools/call` writes — and one module (`server.py`) wires them onto a stdlib
`http.server.ThreadingHTTPServer`, serves the prebuilt console bundle, and
exposes the start/bind functions the CLI and the MCP row call.
"""
from .server import Door, create_door, is_bound, start
from .routes import route_get, route_mcp

__all__ = ["Door", "create_door", "is_bound", "start", "route_get", "route_mcp"]
