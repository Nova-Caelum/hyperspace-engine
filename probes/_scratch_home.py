"""probes/_scratch_home.py — `~` for a probe that provisions a throwaway
project.

`provision_env` records every env it builds in `~/.hyperspace/envs.json`
(`hyperspace/provenance.py`), and the plugin's server starts only a recorded
env. So a probe points `~` (HOME, and USERPROFILE for Windows) at a scratch
folder while it provisions, and every process it starts afterwards — the
server, `claude`, `hyperspace` — inherits the same folder. The user's real
record is never written. uv is told where its real cache is before `~`
moves, so a probe's install is as fast as it was.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path


def _uv_cache() -> dict:
    if os.environ.get("UV_CACHE_DIR") or shutil.which("uv") is None:
        return {}
    try:
        proc = subprocess.run(["uv", "cache", "dir"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    cache = proc.stdout.strip()
    return {"UV_CACHE_DIR": cache} if proc.returncode == 0 and cache else {}


@contextmanager
def scratch_home(home: str | Path):
    """Sets HOME and USERPROFILE to `home` (created if needed) for the block,
    then puts back whatever was there."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    changes = {**_uv_cache(), "HOME": str(home), "USERPROFILE": str(home)}
    saved = {key: os.environ.get(key) for key in changes}
    os.environ.update(changes)
    try:
        yield home
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
