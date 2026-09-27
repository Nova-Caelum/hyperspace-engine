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

#: `generate.py`'s own drift check (`--check`, and this file's parametrized
#: test above it) only ever iterates `RENDERERS` — it has no code path that
#: scans `docs/reference/` for a file it does not know about, so a new
#: hand-written file dropped in that directory is invisible to both. Rather
#: than teach `generate.py` about non-generated files (it renders from
#: source; a file with no source to render from does not belong in its
#: dict), this is the minimal fix: an explicit allow-list, checked below, so
#: a file that is neither generated nor declared here fails loudly instead
#: of sitting unchecked and undocumented indefinitely. See
#: docs/reference/tripwires.md's own header for the other half of this
#: contract (it declares itself here).
HAND_WRITTEN_REFERENCE_FILES = {
    "tripwires.md",  # hyperspace-engine v0.1.1 part A — hand-authored; carries
                      # its own inverted GENERATED_NOTE-style header instead.
}


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


def test_every_reference_file_is_generated_or_declared_hand_written():
    """Closes the gap a new file like `tripwires.md` would otherwise leave:
    `generate.py --check` and the parametrized test above only ever look at
    `RENDERERS`, so a file sitting beside the generated ones in
    `docs/reference/` that is in neither `RENDERERS` nor
    `HAND_WRITTEN_REFERENCE_FILES` is accounted for nowhere — not checked for
    drift, not declared hand-written. (v0.1.1 part A brief, task 4.)"""
    on_disk = {p.name for p in GENERATE.OUT.glob("*.md")}
    accounted_for = set(GENERATE.RENDERERS) | HAND_WRITTEN_REFERENCE_FILES
    unaccounted = on_disk - accounted_for
    assert not unaccounted, (
        f"docs/reference/ has file(s) neither generated nor declared hand-written: "
        f"{sorted(unaccounted)} — add to RENDERERS (generate.py) or "
        f"HAND_WRITTEN_REFERENCE_FILES (this file)"
    )
