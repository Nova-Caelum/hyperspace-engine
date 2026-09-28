"""hyperspace/_stdio.py — UTF-8 on stdout/stderr, whatever the pipe's default.

A piped stream on Windows defaults to the ANSI code page (cp1252): `—` goes
out as byte 0x97 and `→` / `✔` cannot be encoded at all. Claude Code reads a
command's output as UTF-8. Stdlib only — the bootstrap entry point calls this
before any dependency is installed.
"""
from __future__ import annotations

import sys


def utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
