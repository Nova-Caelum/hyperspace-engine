#!/usr/bin/env python3
"""bin/hyperspace_setup.py — the setup skill's bootstrap command, runnable
BEFORE `.hyperspace/env` exists by any Python >= 3.11 on any OS:

    <python> "${CLAUDE_PLUGIN_ROOT}/bin/hyperspace_setup.py" --dir "<project-dir>" --provision

where `<python>` is `python3`, `py -3`, `python`, or `uv run --no-project
--python ">=3.11"`. One form that parses identically in sh, Git Bash,
PowerShell and cmd — the `PYTHONPATH="…" python3 -m hyperspace.setup` it
replaces was sh-only syntax.

Puts this plugin's root on `sys.path` and hands off to
`hyperspace.setup.__main__.main` — whose import chain is stdlib-only by
design (see the import-chain note atop `hyperspace/setup/provision.py`).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hyperspace.setup.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(prog=Path(__file__).name))
