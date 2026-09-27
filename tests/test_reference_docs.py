"""Drift test for docs/reference/ — the committed reference files must equal
what docs/reference/generate.py renders from source right now.

A code change that moves a flag, a field, a status, a gate constant or an MCP
tool without regenerating the reference fails here, in CI, rather than in a
reader's afternoon. Fix: `python docs/reference/generate.py`, commit the result.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "docs" / "reference" / "generate.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("hyperspace_reference_generate", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


GENERATE = _load_generator()


@pytest.mark.parametrize("name", sorted(GENERATE.RENDERERS))
def test_reference_file_matches_source(name):
    committed = GENERATE.OUT / name
    assert committed.is_file(), f"docs/reference/{name} is missing — run: python docs/reference/generate.py"
    rendered = GENERATE.RENDERERS[name]()
    assert committed.read_text(encoding="utf-8") == rendered, (
        f"docs/reference/{name} has drifted from source — run: python docs/reference/generate.py"
    )


def test_generator_check_mode_passes_on_a_clean_tree():
    assert GENERATE.main(["--check"]) == 0
