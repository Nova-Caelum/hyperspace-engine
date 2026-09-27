"""hyperspace/config.py — the full judge-selection config: reads and writes
`.hyperspace/config.toml`. Replaces the interim `hyperspace/tools/_config.py`
reader (T3.1), which only ever read the one `judge` key; this module owns all
four settings the setup skill writes (`judge`, `model`, `port`, `user`) and the
five-runner selection (T3.2).

Default judge models are CONFIG, not code (Plan T3.2 note) — `DEFAULT_MODELS`
below is the constant the setup skill and `get_judge` fall back to when the
user picks a keyed runner without naming a model; it is not a hidden default
buried in a runner class.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The five runners `judge` may select — the closed set `load_config` and
# `get_judge` both validate against.
JUDGES: tuple[str, ...] = ("openrouter", "anthropic", "claude-code", "codex", "none")

DEFAULT_JUDGE = "none"
DEFAULT_PORT = 8791
DEFAULT_USER = "user"

CONFIG_FILENAME = "config.toml"

# One default model id per keyed provider, cited from real sources read this
# session (never invented — B2/assumption-check):
#   * openrouter -> "qwen/qwen3.7-flash": the source engine's own verified
#     default for its judge runner (`DEFAULT_MODEL = os.environ.get(
#     "VERIFIER_JUDGE_MODEL", "openrouter:qwen/qwen3.7-flash")`) — already in
#     production use as an inexpensive, strong judge model.
#   * anthropic -> "claude-sonnet-4-5": a current, non-deprecated model id per
#     the Anthropic Python SDK's `ModelParam` literal union (context7
#     `/anthropics/anthropic-sdk-python`, `model_param.py`, read 2026-09-26).
#     `DEPRECATED_MODELS` in that same SDK does not list it.
DEFAULT_MODELS: dict[str, str] = {
    "openrouter": "qwen/qwen3.7-flash",
    "anthropic": "claude-sonnet-4-5",
}


@dataclass(frozen=True)
class Config:
    judge: str = DEFAULT_JUDGE
    model: str | None = None
    port: int = DEFAULT_PORT
    user: str = DEFAULT_USER
    project_dir: Path = Path(".")


def _config_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / ".hyperspace" / CONFIG_FILENAME


def load_config(project_dir: str | Path) -> Config:
    """Reads `.hyperspace/config.toml` under `project_dir`. A missing file
    (or one with no `judge` key) resolves to every default. An unreadable or
    malformed TOML file also resolves to defaults — matching the interim
    reader's tolerance for a broken file (there is nothing safe to raise
    about a file we cannot even parse). An explicit but UNKNOWN `judge` value
    is refused loudly: that is a real (if malformed) instruction, not an
    absent one, and silently substituting `none` for it would hide a typo
    from whoever wrote the file.
    """
    project_dir = Path(project_dir)
    path = _config_path(project_dir)
    if not path.exists():
        return Config(project_dir=project_dir)
    try:
        with path.open("rb") as fh:
            data: dict[str, Any] = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return Config(project_dir=project_dir)

    judge = data.get("judge", DEFAULT_JUDGE)
    if not isinstance(judge, str) or judge not in JUDGES:
        raise ValueError(
            f"unknown judge {judge!r} in {path} — must be one of: {', '.join(JUDGES)}"
        )
    model = data.get("model")
    if model is not None and not isinstance(model, str):
        model = str(model)
    port = data.get("port", DEFAULT_PORT)
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    user = data.get("user", DEFAULT_USER)
    if not isinstance(user, str) or not user.strip():
        user = DEFAULT_USER

    return Config(judge=judge, model=model, port=port, user=user, project_dir=project_dir)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_config(project_dir: str | Path, **fields: Any) -> Path:
    """Writes `.hyperspace/config.toml` by hand — no `tomli_w` dependency
    (the brief's decision; this is the only writer the setup skill needs).
    Any field omitted keeps its current value (read via `load_config`, or the
    default if the file does not exist yet).

    Every top-level key this function does not itself own (e.g.
    `worklog_owner`, `worklog_mirror_dir`, `worklog_default_project` —
    read raw by other modules, per `Config`'s own module docstring on why
    those never get a field here) is preserved verbatim across a rewrite.
    Without this, a re-provision (`init --provision`, a setup-skill re-run)
    would silently delete any such key the day it becomes load-bearing for a
    sibling plugin's coupling to this one (v0.1.2 fix)."""
    project_dir = Path(project_dir)
    current = load_config(project_dir)
    merged = {
        "judge": fields.get("judge", current.judge),
        "model": fields.get("model", current.model),
        "port": fields.get("port", current.port),
        "user": fields.get("user", current.user),
    }
    if merged["judge"] not in JUDGES:
        raise ValueError(f"unknown judge {merged['judge']!r} — must be one of: {', '.join(JUDGES)}")

    path = _config_path(project_dir)
    extra: dict[str, Any] = {}
    if path.is_file():
        try:
            with path.open("rb") as fh:
                raw = tomllib.load(fh)
            extra = {k: v for k, v in raw.items() if k not in merged}
        except (OSError, tomllib.TOMLDecodeError):
            extra = {}

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"judge = {_toml_scalar(merged['judge'])}"]
    if merged["model"] is not None:
        lines.append(f"model = {_toml_scalar(merged['model'])}")
    lines.append(f"port = {_toml_scalar(int(merged['port']))}")
    lines.append(f"user = {_toml_scalar(merged['user'])}")
    for key, value in extra.items():
        lines.append(f"{key} = {_toml_scalar(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
