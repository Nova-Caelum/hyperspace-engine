"""The setup entry points fail plainly on a Python older than 3.11.

macOS ships Python 3.9.6 as `/usr/bin/python3`. `hyperspace/config.py` imports
`tomllib` (3.11+), so on that interpreter the bootstrap commands used to die
with `ModuleNotFoundError: No module named 'tomllib'` and a traceback, before
any message could say what is wrong. `hyperspace/_pyfloor.py` is a stdlib-only
guard that runs first and exits with one plain sentence instead.

Three layers, so the logic is covered even where no old interpreter exists:

* the guard function, in-process, on every Python;
* the guarded files parse under the Python 3.8 grammar and call the guard
  before anything imports `tomllib` (static, on every Python);
* the two bare-interpreter entry points, run as subprocesses under a real
  Python older than 3.11 (skipped with a reason where the machine has none).
"""
from __future__ import annotations

import ast
import importlib
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The two commands that run on a bare interpreter, before `.hyperspace/env`.
ENTRY_POINTS = {
    "bin/hyperspace_setup.py": lambda python: [
        python, str(ROOT / "bin" / "hyperspace_setup.py"), "--help"
    ],
    "python -m hyperspace.setup": lambda python: [python, "-m", "hyperspace.setup", "--help"],
}

# Every file Python parses before the guard has had its chance to refuse.
PARSED_BEFORE_THE_GUARD = (
    "hyperspace/__init__.py",
    "hyperspace/_pyfloor.py",
    "hyperspace/setup/__init__.py",
    "hyperspace/setup/__main__.py",
    "bin/hyperspace_setup.py",
)
# The files that must call the guard themselves, ahead of any heavier import.
GUARDING_FILES = (
    "hyperspace/setup/__init__.py",
    "hyperspace/setup/__main__.py",
    "bin/hyperspace_setup.py",
)
# Importing any of these reaches `hyperspace.config` and so `tomllib`.
REACHES_TOMLLIB = ("tomllib", "config", "provision", "store", "__main__")


def _floor():
    return importlib.import_module("hyperspace._pyfloor")


# ── the guard, in-process, on every Python ───────────────────────────────


@pytest.mark.parametrize("version", [(3, 9, 6), (3, 10, 99), (3, 8, 0), (2, 7, 18)])
def test_guard_rejects_a_python_older_than_3_11(version):
    with pytest.raises(SystemExit) as caught:
        _floor().require_python(version)
    message = caught.value.code
    assert isinstance(message, str), "a sentence for stderr (exit status 1), not a bare number"
    assert "3.11" in message
    assert ".".join(str(part) for part in version) in message
    assert len(message.strip().splitlines()) == 1
    assert len(re.split(r"(?<=[.!?])\s+", message.strip())) == 1, "exactly one sentence"


@pytest.mark.parametrize("version", [(3, 11, 0), (3, 11, 15), (3, 12, 1), (3, 14, 6), (4, 0, 0)])
def test_guard_accepts_3_11_and_newer(version):
    assert _floor().require_python(version) is None
    assert _floor().unsupported_message(version) is None


def test_guard_defaults_to_the_running_interpreter():
    # The suite itself runs on >= 3.11, so the no-argument form must accept it.
    assert _floor().require_python() is None


def test_setup_and_guard_share_one_floor():
    # `hyperspace.setup` re-exports a *function* named `provision`, so import
    # the module by its dotted name rather than `from hyperspace.setup import`.
    provision = importlib.import_module("hyperspace.setup.provision")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert provision.MIN_PYTHON == _floor().MIN_PYTHON == (3, 11)
    assert pyproject["project"]["requires-python"] == ">=3.11"


# ── the guarded files, static ────────────────────────────────────────────


@pytest.mark.parametrize("rel", PARSED_BEFORE_THE_GUARD)
def test_files_python_parses_before_the_guard_are_valid_3_8_syntax(rel):
    # An old interpreter parses a whole file before running line 1, so one
    # construct newer than its grammar turns the plain sentence into a
    # SyntaxError. (`X | Y` in an annotation is syntax everywhere; it is the
    # real-interpreter test below that catches one evaluated at import.)
    source = (ROOT / rel).read_text(encoding="utf-8")
    ast.parse(source, filename=rel, feature_version=(3, 8))


def _imported_modules(node):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return ["." * node.level + (node.module or "")]
    return []


def _is_guard_call(node):
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", None) == "require_python"
    )


@pytest.mark.parametrize("rel", GUARDING_FILES)
def test_guard_is_called_before_anything_that_imports_tomllib(rel):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=rel)
    guard_seen = False
    for node in tree.body:
        if _is_guard_call(node):
            guard_seen = True
            continue
        for module in _imported_modules(node):
            if any(word in module for word in REACHES_TOMLLIB):
                assert guard_seen, f"{rel} line {node.lineno} imports {module!r} before the guard runs"
    assert guard_seen, f"{rel} never calls require_python()"


# ── the entry points, as subprocesses ────────────────────────────────────


def _bare_env():
    """The caller's environment minus anything that could change which modules
    the interpreter finds, and with no `.pyc` written into the checkout."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run(argv):
    proc = subprocess.run(argv, cwd=str(ROOT), env=_bare_env(), capture_output=True, timeout=60)
    return proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", "replace")


def _version_of(python):
    try:
        proc = subprocess.run(
            [python, "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return tuple(int(part) for part in proc.stdout.strip().split("."))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _find_old_python():
    """(path, version) of an interpreter older than 3.11, or None. Looks at the
    stock macOS one first, then any python3.8-3.10 or an old `python3` on PATH."""
    names = ("python3.8", "python3.9", "python3.10", "python3", "python")
    candidates = ["/usr/bin/python3"] + [shutil.which(name) for name in names]
    seen = set()
    for python in candidates:
        if not python or python in seen or not Path(python).exists():
            continue
        seen.add(python)
        version = _version_of(python)
        if version is not None and version < (3, 11, 0):
            return python, version
    return None


@pytest.fixture(scope="module")
def old_python():
    found = _find_old_python()
    if found is None:
        pytest.skip(
            "no Python older than 3.11 on this machine "
            "(looked for /usr/bin/python3 and python3.8, 3.9, 3.10, python3, python on PATH)"
        )
    return found


@pytest.mark.parametrize("entry", list(ENTRY_POINTS))
def test_old_python_exits_with_one_sentence_and_no_traceback(old_python, entry):
    python, version = old_python
    code, output = _run(ENTRY_POINTS[entry](python))
    assert code != 0, f"expected a non-zero exit, got {code}:\n{output}"
    assert "Traceback" not in output, f"{entry} on Python {version} crashed:\n{output}"
    assert "3.11" in output, f"no sentence naming 3.11:\n{output}"
    assert ".".join(str(part) for part in version) in output, f"does not name the running Python:\n{output}"
    assert len(output.strip().splitlines()) == 1, f"more than one line:\n{output}"
    assert len(re.split(r"(?<=[.!?])\s+", output.strip())) == 1, f"more than one sentence:\n{output}"


@pytest.mark.parametrize("entry", list(ENTRY_POINTS))
def test_current_python_still_starts(entry):
    code, output = _run(ENTRY_POINTS[entry](sys.executable))
    assert code == 0, f"{entry} failed on the interpreter running the suite:\n{output}"
    assert "usage:" in output
