"""hyperspace/http/server.py — the loopback door's socket layer (row T4.2).

Stdlib `http.server` only — no web framework (Decision.md, locked). Binds
`127.0.0.1`/`localhost` only; `Door.__init__` raises `ValueError` before a
socket is ever opened for any other host. No CORS — same-origin by design,
so none is added. Logs one line per request to stderr; the request body is
never logged (hook-secret-handling discipline applies to any stdout/stderr
emission this process makes, and a request body is not this door's to echo).
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from ..store import Store
from .routes import route_delete, route_get, route_mcp, route_patch, route_post

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost")

# `ui/dist/`, resolved relative to the package root — `hyperspace/http/server.py`
# is three levels under the repo root (`hyperspace/http/server.py` ->
# `hyperspace/http` -> `hyperspace` -> repo root), so `parents[2]` is the repo
# root and `ui/dist` sits beside `hyperspace/`.
_DIST_DIR = Path(__file__).resolve().parents[2] / "ui" / "dist"
_PLACEHOLDER_DIR = Path(__file__).resolve().parent / "placeholder"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".map": "application/json",
}


def _static_dir() -> Path:
    """`ui/dist/` if the bundle row has landed; otherwise the placeholder this
    row ships so the door still serves *something* at `/` (brief step: "if it
    is absent in your worktree, serve a placeholder index.html")."""
    if (_DIST_DIR / "index.html").is_file():
        return _DIST_DIR
    return _PLACEHOLDER_DIR


class Door(ThreadingHTTPServer):
    """The loopback door. Refuses to construct on any host but
    `127.0.0.1`/`localhost` — Decision.md: "never bind beyond 127.0.0.1".

    Exclusive bind on every OS: a second door on a busy port must fail with
    EADDRINUSE so the MCP server adopts the running one and `hyperspace
    serve` refuses. POSIX gets that with SO_REUSEADDR (which only permits
    reuse of a TIME_WAIT port); on Windows SO_REUSEADDR lets a second socket
    bind a port that is already listening, so there the door sets
    SO_EXCLUSIVEADDRUSE instead."""

    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, server_address: tuple[str, int], handler_class: type, *, store_path: Path):
        host, _port = server_address
        if host not in _LOOPBACK_HOSTS:
            raise ValueError(
                f"refusing to bind {host!r} — the loopback door binds "
                f"127.0.0.1/localhost only, never beyond it"
            )
        self.store_path = store_path
        super().__init__(server_address, handler_class)


class DoorRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ── logging — one line per request to stderr, never a body ─────────────

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002 — stdlib override signature
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

    # ── per-request store — sqlite3 connections are not thread-safe, and
    # ThreadingHTTPServer runs each request on its own thread, so each request
    # opens (and closes) its own `Store` against the same on-disk file ─────

    def _open_store(self) -> Store:
        return Store.open(self.server.store_path)

    def _write_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_file(self, path: Path, content_type: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, url_path: str) -> None:
        static_dir = _static_dir()
        index_file = static_dir / "index.html"

        if not url_path.startswith("/assets/"):
            # `/` and every unknown non-API path — SPA fallback.
            if index_file.is_file():
                self._write_file(index_file, "text/html; charset=utf-8")
            else:
                self._write_json(404, {"error": "index.html not found"})
            return

        # `/assets/<file>` — resolve, then confirm the result is still under
        # `static_dir` before opening it (path-traversal guard: a `..` segment
        # in `url_path` must never escape the bundle directory).
        rel = url_path.lstrip("/")
        resolved_root = static_dir.resolve()
        candidate = (static_dir / rel).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            self._write_json(404, {"error": "not found"})
            return
        if not candidate.is_file():
            self._write_json(404, {"error": "not found"})
            return
        content_type = _CONTENT_TYPES.get(candidate.suffix, "application/octet-stream")
        self._write_file(candidate, content_type)

    # ── HTTP verbs ───────────────────────────────────────────────────────────

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            store = self._open_store()
            try:
                status, body = route_get(store, self.path)
            finally:
                store.close()
            self._write_json(status, body)
            return
        self._serve_static(self.path)

    def _read_json_body(self) -> Any:
        """The parsed JSON body, or `None` when it is empty or not JSON."""
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return None

    def do_PATCH(self) -> None:
        request_obj = self._read_json_body()  # always drained: the connection is kept alive
        store = self._open_store()
        try:
            status, body = route_patch(store, self.path, request_obj)
        finally:
            store.close()
        self._write_json(status, body)

    def do_POST(self) -> None:
        if self.path.startswith("/api/"):
            request_obj = self._read_json_body()
            store = self._open_store()
            try:
                status, body = route_post(store, self.path, request_obj)
            finally:
                store.close()
            self._write_json(status, body)
            return

        if self.path != "/mcp":
            self._write_json(404, {"error": f"not found: {self.path}"})
            return

        request_obj = self._read_json_body()
        store = self._open_store()
        try:
            response = route_mcp(store, request_obj)
        finally:
            store.close()
        self._write_json(200, response)

    def do_DELETE(self) -> None:
        self._read_json_body()  # drained: the connection is kept alive
        store = self._open_store()
        try:
            status, body = route_delete(store, self.path)
        finally:
            store.close()
        self._write_json(status, body)


# ── construction / lifecycle helpers ────────────────────────────────────────

def create_door(store_path: Path, host: str = "127.0.0.1", port: int = 8791) -> Door:
    """Binds and starts listening — the socket is bound and queuing
    connections as soon as this returns; nothing is served until
    `serve_forever()` runs the request loop (the CLI does this in the
    foreground; `start()` below does it on a daemon thread)."""
    return Door((host, port), DoorRequestHandler, store_path=store_path)


def start(
    store_path: Path,
    port: int,
    host: str = "127.0.0.1",
    open_browser: bool = False,
    opener: Callable[[str], object] = webbrowser.open,
) -> Door:
    """Binds, serves in a daemon thread, and returns after bind — the shape
    the MCP row calls to lazy-start the door without blocking its own stdio
    loop."""
    door = create_door(store_path, host, port)
    thread = threading.Thread(target=door.serve_forever, daemon=True)
    thread.start()
    if open_browser:
        bound_host, bound_port = door.server_address[0], door.server_address[1]
        opener(f"http://{bound_host}:{bound_port}/")
    return door


def is_bound(port: int, host: str = "127.0.0.1") -> bool:
    """True if something is already listening on `host:port` — a connect
    probe, not a bind attempt (the MCP row's "adopt if bound" check)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False
