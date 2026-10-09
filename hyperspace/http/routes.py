"""hyperspace/http/routes.py — the console's REST-read and JSON-RPC-write
contract as pure functions (row T4.2): `route_get`, `route_mcp`, and the console's
REST update of a work item, `route_patch`.

No socket code lives here on purpose — `route_get(store, path) -> (status,
body_obj)` and `route_mcp(store, request_obj) -> response_obj` take and
return plain Python objects, so `server.py` (or, later, the local MCP row)
can reuse the JSON-RPC envelope logic in `route_mcp` without a socket in
sight. Field shapes come straight off `Store`/`call_tool` results — nothing
is added that the console does not read, and nothing is renamed (brief step 3).

Reads go straight to `Store` (brief: "answers the console page's reads from
the store"); only writes route through `call_tool`/the graph-tool table,
because the graph tools own contract validation and filing — a read has
nothing to validate.
"""
from __future__ import annotations

import json
import re
import uuid as _uuid
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from ..store import Store
from ..tools.registry import ToolError, call_tool
from ..tools.work_items import console_patch_work_item

_PROJECTS = re.compile(r"^/api/projects$")
_PROJECT_SUB = re.compile(r"^/api/projects/([^/]+)/(work-items|modules|cycles)$")
_MODULE_ITEM = re.compile(r"^/api/modules/([^/]+)$")
_WORK_ITEM_ITEM = re.compile(r"^/api/work-items/([^/]+)$")
_INITIATIVES = re.compile(r"^/api/initiatives$")
_INITIATIVE_LINKS = re.compile(r"^/api/initiatives/([^/]+)/links$")
_INITIATIVE_ITEM = re.compile(r"^/api/initiatives/([^/]+)$")


def _is_uuid(value: str) -> bool:
    try:
        _uuid.UUID(value)
        return True
    except ValueError:
        return False


def _resolve_module(store: Store, seg: str, project_code: str | None) -> dict | None:
    """The console sends both shapes (App.tsx:650, 662, 708 — detail routes
    key on external_id; row UUIDs also appear via `externalIdByUuid` misses).
    Dispatch on shape is not a translation layer — it is exactly what the
    brief's route asks for ("resolve BOTH a uuid and an external_id")."""
    if _is_uuid(seg):
        row = store.get_module(id=seg)
        if row is not None:
            return row
    return store.get_module(external_id=seg, project_code=project_code)


def _resolve_work_item(store: Store, seg: str, project_code: str | None) -> dict | None:
    if _is_uuid(seg):
        row = store.get_work_item(id=seg)
        if row is not None:
            return row
    return store.get_work_item(external_id=seg, project_code=project_code)


def _resolve_initiative(store: Store, seg: str) -> dict | None:
    if _is_uuid(seg):
        row = store.get_initiative(id=seg)
        if row is not None:
            return row
    return store.get_initiative(external_id=seg)


def _split_api_path(path: str) -> tuple[str, str | None]:
    """The percent-decoded path and its `?project_code=`. The console builds
    `/api/work-items/${encodeURIComponent(id)}`, and a work item's external_id
    is `<project>:<slug>`, so the colon arrives as `%3A`."""
    split = urlsplit(path)
    return unquote(split.path), (parse_qs(split.query).get("project_code") or [None])[0]


def route_get(store: Store, path: str) -> tuple[int, Any]:
    """Dispatches a GET `path` (any query string is parsed and ignored unless
    a route names it explicitly — `project_code` disambiguates a
    project-scoped external_id on the module/work-item detail routes, mirroring
    the console's own `?project_code=...` on `/api/modules/{id}`)."""
    clean_path, project_code = _split_api_path(path)

    if not clean_path.startswith("/api/"):
        return 404, {"error": f"not found: {clean_path}"}

    if _PROJECTS.match(clean_path):
        return 200, store.list_projects()

    m = _PROJECT_SUB.match(clean_path)
    if m:
        code, kind = m.groups()
        if kind == "work-items":
            return 200, store.list_work_items(project_code=code)
        if kind == "modules":
            return 200, store.list_modules(project_code=code)
        return 200, store.list_cycles(project_code=code)

    m = _INITIATIVE_LINKS.match(clean_path)
    if m:
        init = _resolve_initiative(store, m.group(1))
        if init is None:
            return 404, {"error": f"initiative not found: {m.group(1)!r}"}
        return 200, store.list_initiative_links(init["id"])

    m = _MODULE_ITEM.match(clean_path)
    if m:
        row = _resolve_module(store, m.group(1), project_code)
        if row is None:
            return 404, {"error": f"module not found: {m.group(1)!r}"}
        return 200, row

    m = _WORK_ITEM_ITEM.match(clean_path)
    if m:
        row = _resolve_work_item(store, m.group(1), project_code)
        if row is None:
            return 404, {"error": f"work item not found: {m.group(1)!r}"}
        return 200, row

    if _INITIATIVES.match(clean_path):
        return 200, store.list_initiatives()

    m = _INITIATIVE_ITEM.match(clean_path)
    if m:
        row = _resolve_initiative(store, m.group(1))
        if row is None:
            return 404, {"error": f"initiative not found: {m.group(1)!r}"}
        return 200, row

    return 404, {"error": f"not found: {clean_path}"}


_TOOL_ERROR_STATUS = {"validation": 400, "refused": 400, "not_found": 404, "conflict": 409}


def route_patch(store: Store, path: str, body_obj: Any) -> tuple[int, Any]:
    """`PATCH /api/work-items/<id>` — the bundled page's partial update of a work
    item (its save, status and reorder controls). This is the console's door, so
    a change of `state` into `done` is stamped `hyperspace-console`
    (`console_patch_work_item`, called from nowhere else). Replies in the shape
    the page unwraps: `{"status": "updated", "row": ...}`, or `{"error": ...}`."""
    clean_path, project_code = _split_api_path(path)
    m = _WORK_ITEM_ITEM.match(clean_path)
    if not m:
        return 404, {"error": f"not found: {clean_path}"}
    if not isinstance(body_obj, dict):
        return 400, {"error": "request body must be a JSON object"}
    row = _resolve_work_item(store, m.group(1), project_code)
    if row is None:
        return 404, {"error": f"work item not found: {m.group(1)!r}"}
    try:
        return 200, console_patch_work_item(store, row, body_obj)
    except ToolError as exc:
        return _TOOL_ERROR_STATUS[exc.code], {"error": exc.message}
    except Exception as exc:  # noqa: BLE001 — never a traceback over the wire
        return 500, {"error": f"{type(exc).__name__}: {exc}"}


def _is_tool_error_result(result: Any) -> bool:
    return (
        isinstance(result, dict)
        and set(result.keys()) == {"error"}
        and isinstance(result["error"], dict)
        and "message" in result["error"]
    )


def route_mcp(store: Store, request_obj: Any) -> dict:
    """A JSON-RPC 2.0 `tools/call` envelope over `call_tool`.

    `request_obj` is whatever the caller already parsed from the request body
    — `None` (unparsable/empty body) is a legal input and produces the same
    `-32600` shape as any other malformed request, so the HTTP layer never
    needs a second error path for a JSON-decode failure.

    This is the console's door, so it is the only caller that passes
    `console=True` to `call_tool`: a `state="done"` write that arrives here is
    stamped `hyperspace-console`. The stdio MCP server never does."""
    req_id = request_obj.get("id") if isinstance(request_obj, dict) else None

    if not isinstance(request_obj, dict) or request_obj.get("method") != "tools/call":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32600, "message": "invalid request: expected JSON-RPC 2.0 method 'tools/call'"},
        }

    params = request_obj.get("params")
    if not isinstance(params, dict) or "name" not in params:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32600, "message": "invalid request: params.name is required"},
        }

    name = params["name"]
    arguments = params.get("arguments") or {}

    try:
        result = call_tool(store, name, arguments, console=True)
    except Exception as exc:  # noqa: BLE001 — nothing may escape as a 500/traceback;
        # `call_tool` already wraps its own tool-function exceptions into
        # {"error": ...}, so reaching this branch means call_tool's own
        # dispatch code raised — still never let it escape unwrapped.
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"},
        }

    if _is_tool_error_result(result):
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": result["error"]["message"]}], "isError": True},
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
    }
