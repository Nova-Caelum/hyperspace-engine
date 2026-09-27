# Vendored from the Nova Caelum graph_library primitives/completion/claim.py, 2026-09-26.
# Adapted for hyperspace-engine; see THIRD_PARTY_NOTICES.md.
"""`CompletionClaim` — what an agent submits when it says a row is done.

The package IS the statement of work. It carries the row
identity and a typed list of what was touched, and nothing an account could
hide in. There is no free-text field. `extra="forbid"` refuses one.

Paths may be absolute, `~`-prefixed, or project-relative (resolved against the
user's project root — the directory holding `.hyperspace/`). There is no traversal
ban here — the ban the old contract carried never prevented its own threat
(handoff §6), and this verifier is read-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

Effect = Literal["created", "modified", "deleted"]


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


class TouchedPath(_Strict):
    path: str = Field(min_length=1, max_length=1_000)
    effect: Effect

    @field_validator("path")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("path must not be blank")
        if "\n" in v or "\r" in v or "\x00" in v:
            raise ValueError("path must be a single line")
        return v


class ManualAttestation(_Strict):
    """The one typed way a human attestation enters: a
    `manual` criterion discharges only against an exact-statement match here,
    with `attested_by` equal to the configured user identity (`Deps.user_identity`)
    — an agent cannot attest on the user's behalf."""
    statement: str = Field(min_length=10, max_length=2_000)
    attested_by: str = Field(min_length=1, max_length=100)
    verbatim: str = Field(min_length=1, max_length=4_000)

    @field_validator("statement", "attested_by", "verbatim")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class CompletionClaim(_Strict):
    project: str = Field(min_length=1, max_length=255)
    external_id: str = Field(min_length=1, max_length=255)
    touched: list[TouchedPath] = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=128)
    proposer_identity: str = Field(min_length=1, max_length=100)
    proposer_surface: str = Field(min_length=1, max_length=64)
    manual_attestations: list[ManualAttestation] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def no_duplicate_paths(self) -> "CompletionClaim":
        seen: set[str] = set()
        dupes = [t.path for t in self.touched if t.path in seen or seen.add(t.path)]
        if dupes:
            raise ValueError(
                f"touched: duplicate path(s) {dupes!r} — name each path once, with one effect"
            )
        return self


def resolve_touched_path(raw: str, project_root: Path) -> Path:
    """Absolute stays; `~` expands; anything else is project-relative."""
    p = Path(raw)
    if raw.startswith("~"):
        p = p.expanduser()
    elif not p.is_absolute():
        p = project_root / p
    return p.resolve()


def repair_message(exc: ValidationError) -> str:
    """Turn a pydantic error into a repair instruction the caller can act on:
    one line per field, `field: what would satisfy it`."""
    lines = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ())) or "(package)"
        msg = err.get("msg", "invalid")
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        lines.append(f"{loc}: {msg}")
    return "\n".join(lines)
