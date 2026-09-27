#!/usr/bin/env python3
"""Pre-gate validator for an N1 `tests.json` (the Understand node's step 6).

Loads the file, strips `_`-prefixed annotation keys at every depth, and
validates it as `hyperspace.contracts.candidate.CandidateWorkItem` — the same
contract, loaded the same way, as `node_gates.check_understanding`.

    .hyperspace/env/bin/python "${CLAUDE_PLUGIN_ROOT}/bin/validate_candidate.py" <tests.json>

Exit 0 prints `VALID`. Exit 1 prints `INVALID` and pydantic's own message.
Exit 2: the file is unreadable, or the contract cannot be loaded (for example
pydantic is missing from this interpreter) — an environment problem, not a
verdict on the file.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import node_gates  # noqa: E402 — shares the contract loader and the annotation strip


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: validate_candidate.py <tests.json>", file=sys.stderr)
        return 2
    path = Path(args[0])
    raw = node_gates._load_json_object(path)
    if raw is None:
        print(f"unreadable, not JSON, or not a JSON object: {path}", file=sys.stderr)
        return 2
    contract = node_gates._load_contract()
    if isinstance(contract, str):
        print(contract, file=sys.stderr)
        return 2
    candidate_model, validation_error = contract
    try:
        candidate_model(**node_gates._strip_annotations(raw))
    except validation_error as exc:
        print(f"INVALID {path}\n{exc}")
        return 1
    print(f"VALID {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
