"""hyperspace/_pyfloor.py — the Python floor, checked before anything heavier loads.

The engine's config reader imports `tomllib`, which exists from Python 3.11. On
an older interpreter (the stock macOS `/usr/bin/python3` is 3.9.6) the setup
commands used to die inside that import with a `ModuleNotFoundError` and a
traceback, which says nothing about what to do. The two bare-interpreter entry
points call `require_python()` first instead and exit with one plain sentence.

This module is stdlib only and written to parse on any Python 3 — no
annotations, no f-strings, nothing newer than the grammar of the interpreters
it has to refuse. It must stay importable without touching `hyperspace.config`,
`hyperspace.setup.provision` or anything else that reaches `tomllib`.
"""
import sys

# The one definition of the floor. `hyperspace.setup.provision.MIN_PYTHON` is
# this same object, so the guard and the provisioner cannot drift apart.
MIN_PYTHON = (3, 11)


def unsupported_message(version_info=None):
    """The one-sentence refusal for `version_info` (default: this interpreter's
    own `sys.version_info`), or None when it meets the floor. A test passes a
    fake tuple to exercise the refusal without a second Python on the machine."""
    version_info = sys.version_info if version_info is None else version_info
    parts = tuple(version_info)[:3]
    if parts[:2] >= MIN_PYTHON:
        return None
    return (
        "Hyperspace Engine needs Python {need} or newer, but this is Python {have}; "
        "install a newer Python (or run it with uv) and try again."
    ).format(
        need=".".join(str(part) for part in MIN_PYTHON),
        have=".".join(str(part) for part in parts),
    )


def require_python(version_info=None):
    """Return None when `version_info` meets the floor. Otherwise exit with
    status 1 and the refusal sentence on stderr — no traceback."""
    message = unsupported_message(version_info)
    if message is not None:
        sys.exit(message)
