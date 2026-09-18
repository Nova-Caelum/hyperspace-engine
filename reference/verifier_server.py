"""`nova-caelum-verifier` — first-party stdio MCP. Two tools.

Runs on the Mac, where the vault, the code folder and every git working tree
are in view (handoff D4: Railway has no checkout). Launched by `mcp-run.sh` ×3
with the absolute venv interpreter (L4): OpenRouter key · worker bearer ·
committer bearer, all read from env at call time and never logged.

Progress notifications are NOT surfaced to the calling model by Claude Code
(probed 2026-09-06), so junctions land in the state file at every boundary and
the return carries the trail + `state_path`. Stated, not pretended.
"""

# NOTE: no `from __future__ import annotations` here — MCPServer builds the
# tool argument model from REAL annotations; stringified `Literal` cannot be
# resolved in its namespace (probed 2026-09-06, PydanticUserError).
import os
import sys
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ValidationError

GRAPH_LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GRAPH_LIB))

from primitives.completion.claim import CompletionClaim, repair_message  # noqa: E402
from primitives.completion.pipeline import VAULT_ROOT_DEFAULT, complete_workitem as _run, production_deps  # noqa: E402

VAULT_ROOT = Path(os.environ.get("NC_VAULT_ROOT", str(VAULT_ROOT_DEFAULT))).resolve()

mcp = MCPServer("nova-caelum-verifier")


class Touched(BaseModel):
    path: str
    effect: Literal["created", "modified", "deleted"]


class ManualAttestationIn(BaseModel):
    statement: str
    attested_by: str
    verbatim: str


@mcp.tool()
async def complete_workitem(
    project: str,
    external_id: str,
    touched: list[Touched],
    idempotency_key: str,
    proposer_identity: str,
    proposer_surface: str,
    manual_attestations: list[ManualAttestationIn] | None = None,
) -> dict:
    """Close a Task Graph row as `done` by independent verification, synchronously.

    The package IS the statement of work: the row identity and a typed list of
    the paths this work created, modified or deleted (absolute, ~-prefixed, or
    vault-relative). No narrative field exists.

    Five steps, state written at every junction: vet (row, typed criteria,
    presence prescreen) → criteria quality (LLM, no world) → landing check
    (delta since the row was filed — already-true-at-filing never discharges;
    a `manual` criterion discharges only against a `manual_attestations` entry
    with an exact `statement` match and `attested_by="daniel"`, e.g.
    `{"statement": "<the criterion's exact statement>", "attested_by": "daniel",
    "verbatim": "yes, confirmed"}` — otherwise it is left `uncertain`, never a
    silent pass) → evidence judge (LLM over the delta, typed criteria only) →
    compose and commit under the committer identity, confirmed by readback.

    Returns exactly one of: done · refused (with the repair) · unverifiable
    (routes to Daniel) · already_done. Never a receipt.
    """
    try:
        claim = CompletionClaim(
            project=project, external_id=external_id,
            touched=[t.model_dump() for t in touched],
            idempotency_key=idempotency_key,
            proposer_identity=proposer_identity, proposer_surface=proposer_surface,
            manual_attestations=[a.model_dump() for a in (manual_attestations or [])],
        )
    except ValidationError as exc:
        return {"outcome": "refused", "reason": "package: " + repair_message(exc)}
    deps = production_deps(VAULT_ROOT)
    return await _run(claim, deps)


@mcp.tool()
async def verifier_selftest() -> dict:
    """Report, from THIS process tree, whether the verifier can run: interpreter,
    vault root, secret PRESENCE (lengths only — never values), judge imports,
    and a live identity check on both ops bearers."""
    out: dict = {"python": sys.executable, "vault_root": str(VAULT_ROOT),
                 "vault_root_exists": VAULT_ROOT.is_dir()}
    for k in ("OPENROUTER_API_KEY", "GMWORKER_OPS_BEARER", "GMCOMMITTER_OPS_BEARER"):
        out[k] = len(os.environ.get(k, ""))
    try:
        import pydantic_ai
        out["pydantic_ai"] = pydantic_ai.__version__
        from primitives.judges import _runtime  # noqa: F401
        out["prompts"] = sorted(p.name for p in (GRAPH_LIB / "primitives" / "judges" / "prompts").glob("*.md"))
    except Exception as exc:
        out["pydantic_ai"] = f"FAIL {type(exc).__name__}: {exc}"
    try:
        from primitives.completion.resolve import OpsClient
        status, _ = OpsClient("GMWORKER_OPS_BEARER").rest_get("/graph-machine/runs/00000000-0000-0000-0000-000000000000")
        out["worker_identity"] = "ok (404 on a phantom run = authenticated)" if status == 404 else f"http {status}"
        payload = OpsClient("GMCOMMITTER_OPS_BEARER").tools_call("get_project", {"code": "graph-machine-testbed"})
        out["committer_identity"] = "ok" if isinstance(payload, dict) and payload.get("code") else str(payload)[:120]
    except Exception as exc:
        out["identity_check"] = f"FAIL {type(exc).__name__}: {str(exc)[:200]}"
    return out


if __name__ == "__main__":
    mcp.run(transport="stdio")
