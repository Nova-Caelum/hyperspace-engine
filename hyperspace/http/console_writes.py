"""hyperspace/http/console_writes.py — the console's REST writes, as graph-tool calls
(row HSE-94, part A).

The console creates things with `POST /api/projects/<code>/{work-items,modules,
cycles}` and `POST /api/initiatives`, edits an initiative with `PATCH
/api/initiatives/<id>`, and links one with `POST /api/initiatives/<id>/links`
(`Caelos/src/app/App.tsx`, `api()`). `plan` turns one such request into the tool
call that performs it; `routes.py` makes the call, so every write goes through the
one function table the MCP path uses and nothing here touches the store but to
read. A body the tool cannot take is refused here with a message that names the
field, and a write the engine has no tool for is refused with a 501 that says so.
"""
from __future__ import annotations

import re
from typing import Any, NamedTuple

from ..store import Store
from ..store.store import LINK_TYPES


class Refusal(Exception):
    """A write the door will not make: an HTTP status and the message the console shows."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ToolCall(NamedTuple):
    name: str
    arguments: dict[str, Any]


_PROJECT_WRITE = re.compile(r"^/api/projects/([^/]+)/(work-items|modules|cycles)$")
_INITIATIVES = re.compile(r"^/api/initiatives$")
_INITIATIVE_ITEM = re.compile(r"^/api/initiatives/([^/]+)$")
_INITIATIVE_LINKS = re.compile(r"^/api/initiatives/([^/]+)/links$")
_INITIATIVE_UNLINK = re.compile(r"^/api/initiatives/([^/]+)/links/([^/]+)/([^/]+)$")
_PROMOTE_TO_MODULE = re.compile(r"^/api/work-items/([^/]+)/promote-to-module$")

#: What each create body may carry — the keys `api()` builds (and the tool's own
#: arguments, which take `project` from the URL). Work items are checked by the tool.
MODULE_KEYS = frozenset({
    "external_id", "name", "description", "state", "team", "folder_path",
    "acceptance_criteria", "acceptance_criteria_ref", "parent_module", "idempotency_key",
})
CYCLE_KEYS = frozenset({
    "external_id", "name", "description", "state", "start_date", "end_date", "idempotency_key",
})
INITIATIVE_KEYS = frozenset({
    "external_id", "title", "description", "state", "doc_paths", "idempotency_key",
})
INITIATIVE_EDIT_KEYS = frozenset({"title", "description", "state", "doc_paths"})

_LINK_ARGUMENT = {"project": "projects", "module": "modules", "work_item": "work_items"}


def _object(body: Any) -> dict:
    if not isinstance(body, dict):
        raise Refusal(400, "request body must be a JSON object")
    return body


def _check_keys(body: dict, allowed: frozenset, label: str = "unknown fields") -> None:
    unknown = set(body) - allowed
    if unknown:
        raise Refusal(400, f"{label}: {', '.join(sorted(unknown))}")


def _require_text(body: dict, key: str) -> None:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Refusal(400, f"{key} is required")


def _initiative(store: Store, seg: str) -> dict:
    """By row id or by external_id — the link routes are keyed on the row id, the rest on external_id."""
    row = store.get_initiative(id=seg) or store.get_initiative(external_id=seg)
    if row is None:
        raise Refusal(404, f"initiative not found: {seg!r}")
    return row


def _create_in_project(store: Store, code: str, kind: str, body: dict) -> ToolCall:
    if store.get_project(code) is None:
        raise Refusal(404, f"project not found: {code!r}")
    if kind == "work-items":
        return ToolCall("upsert_work_item", {**body, "project": code})
    tool, allowed = ("upsert_module", MODULE_KEYS) if kind == "modules" else ("upsert_cycle", CYCLE_KEYS)
    _check_keys(body, allowed)
    _require_text(body, "external_id")
    _require_text(body, "name")
    return ToolCall(tool, {**body, "project": code})


def _create_initiative(body: dict) -> ToolCall:
    _check_keys(body, INITIATIVE_KEYS)
    _require_text(body, "external_id")
    _require_text(body, "title")
    return ToolCall("upsert_initiative", dict(body))


def _edit_initiative(store: Store, seg: str, body: dict) -> ToolCall:
    row = _initiative(store, seg)
    if not body:
        raise Refusal(400, "at least one mutable field is required")
    _check_keys(body, INITIATIVE_EDIT_KEYS, "unknown or immutable fields")
    if "title" in body:
        _require_text(body, "title")
    # `upsert_initiative` takes a title every time; an edit that leaves it alone keeps the stored one.
    return ToolCall("upsert_initiative", {"title": row["title"], **body, "external_id": row["external_id"]})


def _link_initiative(store: Store, seg: str, body: dict) -> ToolCall:
    row = _initiative(store, seg)
    link_type, target = body.get("link_type"), body.get("target_id")
    if link_type not in LINK_TYPES:
        raise Refusal(400, f"link_type must be one of: {', '.join(sorted(LINK_TYPES))}")
    if not isinstance(target, str) or not target.strip():
        raise Refusal(400, "target_id is required")
    return ToolCall("link_initiative_objects", {
        "initiative": row["external_id"], _LINK_ARGUMENT[link_type]: [target],
    })


def plan(store: Store, method: str, path: str, body: Any) -> ToolCall:
    """The tool call for a console write, or a `Refusal`. `path` is percent-decoded,
    without its query string. A request this door has no write for is a 404."""
    if method == "POST":
        m = _PROJECT_WRITE.match(path)
        if m:
            return _create_in_project(store, m.group(1), m.group(2), _object(body))
        if _INITIATIVES.match(path):
            return _create_initiative(_object(body))
        m = _INITIATIVE_LINKS.match(path)
        if m:
            return _link_initiative(store, m.group(1), _object(body))
        if _PROMOTE_TO_MODULE.match(path):
            raise Refusal(
                501,
                "promoting a task to a module is not supported by this engine yet. "
                "Create a module and move the task into it instead.",
            )
    elif method == "PATCH":
        m = _INITIATIVE_ITEM.match(path)
        if m:
            return _edit_initiative(store, m.group(1), _object(body))
    elif method == "DELETE":
        if _INITIATIVE_UNLINK.match(path):
            raise Refusal(501, "unlinking an initiative's target is not supported by this engine yet.")
    raise Refusal(404, f"not found: {path}")
