"""hyperspace.tools — the one function table over the store (row T2.2)."""
from .registry import TOOLS, ToolError, ToolSpec, call_tool

__all__ = ["TOOLS", "ToolError", "ToolSpec", "call_tool"]
