"""Put the engine on sys.path regardless of where the repo is checked out.

In the vault these tests sit deeper in the tree and locate `bin/` by relative
depth. Extracted here, that arithmetic no longer holds, so the path is resolved
from the repository root instead.
"""
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))
