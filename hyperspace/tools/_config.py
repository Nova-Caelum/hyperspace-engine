"""hyperspace/tools/_config.py — a tiny, minimal `.hyperspace/config.toml` reader.

Just the `judge` key, default `"none"`. This is deliberately the smallest
possible reader so `list_agents` can report something other than a hardcoded
stub — the judge row (M3) will move this into `hyperspace/config.py` with the
full five-runner selection (openrouter / anthropic / claude-code / codex /
none); this module is the interim.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

DEFAULT_JUDGE = "none"


def read_judge(config_path: Path) -> str:
    """Returns the configured judge name, or `"none"` if the file is absent,
    unreadable, malformed, or carries no `judge` key."""
    if not config_path.exists():
        return DEFAULT_JUDGE
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return DEFAULT_JUDGE
    judge = data.get("judge")
    return judge if isinstance(judge, str) and judge else DEFAULT_JUDGE
