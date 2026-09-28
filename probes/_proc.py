"""probes/_proc.py — stop a probe's child server, children included.

On Windows a console script (`hyperspace.exe`) or a `cmd /c` launcher is a
parent that spawns `python.exe`; `terminate()` ends only the parent and the
orphan keeps the port and `graph.db` open. `taskkill /T` ends the tree.
"""
from __future__ import annotations

import subprocess
import sys


def stop_tree(proc: subprocess.Popen, timeout: float = 10) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)
