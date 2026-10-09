"""hyperspace/tools/registry.py — the one function table over the store (row T2.2).

Transport-free by decision: every tool below takes `store: Store` as its first
positional argument and keyword arguments after it, and returns a JSON-able
dict or list — no queue, no receipts, no adjudication (the attempter is
deferred). Two transports (stdio MCP, JSON-RPC over HTTP) publish this same
table later; the `input_schema` on each `ToolSpec` is what both of them will
serve, so it is derived once, here.

Import-order note: `ToolError` and `ToolSpec` are defined BEFORE the
`from . import work_items` / `from . import reads` lines below. Both of those
modules do `from .registry import ToolError` at their own top level — a
circular import, but a safe one: by the time Python starts executing
`work_items.py`/`reads.py`, this module is already registered in
`sys.modules` with `ToolError` set as an attribute, so the inner import
resolves against the partially-initialized module object. Reordering the
imports above the class definitions would break this.
"""
from __future__ import annotations

import inspect
import types
from dataclasses import dataclass
from typing import Any, Callable, Union, get_args, get_origin, get_type_hints

from ..contracts.candidate import CandidateWorkItem
from ..store import Store


class ToolError(Exception):
    """Raised by any tool function. `call_tool` converts it into
    `{"error": {"code": ..., "message": ...}}` and never lets any other
    exception escape without being wrapped the same way."""

    CODES = frozenset({"validation", "not_found", "conflict", "refused"})

    def __init__(self, code: str, message: str) -> None:
        if code not in self.CODES:
            raise ValueError(f"unknown ToolError code: {code!r} — must be one of {sorted(self.CODES)}")
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: Callable[..., Any]
    description: str
    input_schema: dict


# ── JSON-schema derivation from a function's type hints ─────────────────────
#
# A small, deliberately non-exhaustive helper: it covers the shapes this
# package's tool functions actually use (str, int, float, bool, list, dict,
# and `X | None`), and falls back to an unconstrained `{}` (still valid JSON
# Schema) for anything richer (e.g. `str | list[str]`). Hand-written schemas
# would be equally acceptable per the brief; this is the "small helper"
# option, applied uniformly so 17 tools don't carry 17 hand-typed schemas.

_UNION_ORIGINS = (Union, types.UnionType)

_SIMPLE_JSON_TYPES: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _json_schema_for(annotation: Any) -> dict:
    origin = get_origin(annotation)

    if origin in _UNION_ORIGINS:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            inner = dict(_json_schema_for(args[0]))
            t = inner.get("type")
            if t and not isinstance(t, list):
                inner["type"] = [t, "null"]
            return inner
        return {}  # a genuine multi-type union (e.g. `str | list[str]`) — permissive

    if origin in (list, tuple, set):
        return {"type": "array"}
    if origin is dict:
        return {"type": "object"}

    if annotation in _SIMPLE_JSON_TYPES:
        return {"type": _SIMPLE_JSON_TYPES[annotation]}
    if annotation is list:
        return {"type": "array"}
    if annotation is dict:
        return {"type": "object"}

    return {}


def _derive_schema(fn: Callable) -> dict:
    """Builds `{"type": "object", "properties": {...}, "required": [...]}`
    from `fn`'s signature, skipping `store` (always the first positional arg)
    and any `*args`/`**kwargs` catch-all (nothing to name a property after)."""
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    properties: dict[str, dict] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname == "store":
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        properties[pname] = _json_schema_for(hints.get(pname, Any))
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {"type": "object", "properties": properties, "required": required}


# ── the table ─────────────────────────────────────────────────────────────
# Imported after ToolError/ToolSpec/_derive_schema are defined — see the
# module docstring's import-order note.
from . import work_items  # noqa: E402
from . import reads  # noqa: E402

TOOLS: dict[str, ToolSpec] = {
    "upsert_work_item": ToolSpec(
        name="upsert_work_item",
        fn=work_items.upsert_work_item,
        description=(
            "File or update a work item: validates the candidate contract, refuses "
            "missing or placeholder criteria, writes the row and an immutable filing "
            "directly (no queue), and mints a fresh filing key on a criteria update. "
            'Refuses state="done" on create and update alike: close a row with '
            "complete_workitem, or ask the user to close it in the console."
        ),
        # `**candidate_fields` carries no named parameters to introspect — the
        # contract model itself IS the schema, and pydantic derives it directly.
        input_schema=CandidateWorkItem.model_json_schema(),
    ),
    "get_work_item": ToolSpec(
        name="get_work_item",
        fn=work_items.get_work_item,
        description="Read one work item by external_id (optionally scoped by project) or by id.",
        input_schema=_derive_schema(work_items.get_work_item),
    ),
    "list_work_items": ToolSpec(
        name="list_work_items",
        fn=work_items.list_work_items,
        description="List work items, filtered by project/state/type/module/parent.",
        input_schema=_derive_schema(work_items.list_work_items),
    ),
    "link_work_items": ToolSpec(
        name="link_work_items",
        fn=work_items.link_work_items,
        description="Create a directed relation between two work items (refuses an unknown relation_type).",
        input_schema=_derive_schema(work_items.link_work_items),
    ),
    "get_graph_run": ToolSpec(
        name="get_graph_run",
        fn=work_items.get_graph_run,
        description="Resolve a filing reference (bare filing id or graph://filing/<id>/item/<ext>#acceptance_criteria) to its filed criteria.",
        input_schema=_derive_schema(work_items.get_graph_run),
    ),
    "upsert_module": ToolSpec(
        name="upsert_module",
        fn=reads.upsert_module,
        description="Create or update a module (refuses acceptance_criteria shorter than 20 or longer than 2000 characters).",
        input_schema=_derive_schema(reads.upsert_module),
    ),
    "get_project": ToolSpec(
        name="get_project",
        fn=reads.get_project,
        description="Read one project by code.",
        input_schema=_derive_schema(reads.get_project),
    ),
    "list_projects": ToolSpec(
        name="list_projects",
        fn=reads.list_projects,
        description="List projects, optionally filtered by status.",
        input_schema=_derive_schema(reads.list_projects),
    ),
    "upsert_project": ToolSpec(
        name="upsert_project",
        fn=reads.upsert_project,
        description="Create or update a project. Not one of the sixteen named by the row's acceptance criterion — included because the console calls it.",
        input_schema=_derive_schema(reads.upsert_project),
    ),
    "append_worklog": ToolSpec(
        name="append_worklog",
        fn=reads.append_worklog,
        description="Append a worklog entry (refuses a summary longer than 280 characters).",
        input_schema=_derive_schema(reads.append_worklog),
    ),
    "get_recent_activity": ToolSpec(
        name="get_recent_activity",
        fn=reads.get_recent_activity,
        description="Read the most recent worklog entries.",
        input_schema=_derive_schema(reads.get_recent_activity),
    ),
    "search_worklog": ToolSpec(
        name="search_worklog",
        fn=reads.search_worklog,
        description="Search worklog entries by project/author/tags/date range.",
        input_schema=_derive_schema(reads.search_worklog),
    ),
    "upsert_cycle": ToolSpec(
        name="upsert_cycle",
        fn=reads.upsert_cycle,
        description="Create or update a planning cycle.",
        input_schema=_derive_schema(reads.upsert_cycle),
    ),
    "assign_cycle_work_items": ToolSpec(
        name="assign_cycle_work_items",
        fn=reads.assign_cycle_work_items,
        description="Assign one or more work items to a cycle.",
        input_schema=_derive_schema(reads.assign_cycle_work_items),
    ),
    "unassign_cycle_work_items": ToolSpec(
        name="unassign_cycle_work_items",
        fn=reads.unassign_cycle_work_items,
        description="Remove one or more work items from a cycle.",
        input_schema=_derive_schema(reads.unassign_cycle_work_items),
    ),
    "upsert_initiative": ToolSpec(
        name="upsert_initiative",
        fn=reads.upsert_initiative,
        description="Create or update a cross-project initiative.",
        input_schema=_derive_schema(reads.upsert_initiative),
    ),
    "link_initiative_objects": ToolSpec(
        name="link_initiative_objects",
        fn=reads.link_initiative_objects,
        description="Link projects, modules, and work items to an initiative.",
        input_schema=_derive_schema(reads.link_initiative_objects),
    ),
    "list_initiative_links": ToolSpec(
        name="list_initiative_links",
        fn=reads.list_initiative_links,
        description="List every link attached to an initiative.",
        input_schema=_derive_schema(reads.list_initiative_links),
    ),
    "list_initiatives": ToolSpec(
        name="list_initiatives",
        fn=reads.list_initiatives,
        description="List initiatives, optionally filtered by state. The seventeenth tool — needed by gear3's principles snapshot.",
        input_schema=_derive_schema(reads.list_initiatives),
    ),
    "list_agents": ToolSpec(
        name="list_agents",
        fn=reads.list_agents,
        description="Local stub: returns the configured judge as the only agent.",
        input_schema=_derive_schema(reads.list_agents),
    ),
}


#: The console's own implementation of a tool, where the console is allowed to
#: do what an agent is not. Today that is one tool: a person may close a row
#: (`hyperspace-console`), an agent may not.
CONSOLE_TOOLS: dict[str, Callable[..., Any]] = {
    "upsert_work_item": work_items.console_upsert_work_item,
}


def call_tool(store: Store, name: str, arguments: dict | None = None, *, console: bool = False) -> Any:
    """Dispatches `name` against `TOOLS`, converting a `ToolError` into
    `{"error": {"code", "message"}}` — and wrapping any OTHER exception the
    same way, so nothing escapes unhandled.

    `console` names the DOOR, and it is a parameter of this function — never a
    key of `arguments`, so nothing a caller sends can set it. The default is the
    agent door; only the HTTP transport (`http/routes.py::route_mcp`) passes
    `console=True`."""
    arguments = arguments or {}
    spec = TOOLS.get(name)
    if spec is None:
        return {"error": {"code": "not_found", "message": f"no such tool: {name!r}"}}
    fn = CONSOLE_TOOLS.get(name, spec.fn) if console else spec.fn
    try:
        return fn(store, **arguments)
    except ToolError as exc:
        return {"error": {"code": exc.code, "message": exc.message}}
    except Exception as exc:  # noqa: BLE001 — the wrap-everything contract (brief step 2)
        return {"error": {"code": "refused", "message": f"{type(exc).__name__}: {exc}"}}
