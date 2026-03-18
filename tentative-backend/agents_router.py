"""
agents_router.py
----------------
FastAPI router that exposes the Agent Catalog to the frontend.

Routes:
  GET  /api/agents              → full catalog (optional ?tier=, ?role=, ?tag= filters)
  GET  /api/agents/{agent_id}   → single agent detail
  POST /api/agents/select       → record a user's agent selection for an AEG node

Mount in app.py with:
    from agents_router import router as agents_router
    app.include_router(agents_router)
"""

import sys
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Make the shared/ directory importable regardless of working directory
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent  # tentative-backend/../  → repo root
_SHARED_DIR = _REPO_ROOT / "shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from agent_catalog import AGENT_CATALOG  # noqa: E402  (import after path manipulation)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/api/agents", tags=["Agent Library"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class AgentSelectRequest(BaseModel):
    """Body for POST /api/agents/select"""
    aeg_node_id: str
    agent_id: str


class AgentSelectResponse(BaseModel):
    status: str
    aeg_node_id: str
    agent: dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
MODEL_TIER_LABELS = {
    "simple":        "Phi-4",
    "intermediate":  "GPT-4o-mini",
    "complex":       "GPT-4o",
    "high-reasoning":"GPT-4o + o1-preview",
}

TIER_LABELS = {
    1: "Module Agent",
    2: "Support Agent",
}


def _enrich(agent: dict) -> dict:
    """Attach human-readable display fields without mutating the catalog."""
    return {
        **agent,
        "model_label": MODEL_TIER_LABELS.get(agent.get("model_tier", ""), agent.get("model_tier", "")),
        "tier_label":  TIER_LABELS.get(agent.get("tier", 0), "Agent"),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/", summary="List all agents in the catalog")
def list_agents(
    tier: Optional[int] = Query(None, description="Filter by tier: 1 (Module) or 2 (Support)"),
    role: Optional[str] = Query(None, description="Case-insensitive role name substring filter"),
    tag:  Optional[str] = Query(None, description="Filter by tag (exact, case-insensitive)"),
):
    """
    Return the full agent catalog with optional filters.

    Examples:
      GET /api/agents
      GET /api/agents?tier=1
      GET /api/agents?role=backend
      GET /api/agents?tag=testing
    """
    results = AGENT_CATALOG

    if tier is not None:
        results = [a for a in results if a.get("tier") == tier]
    if role is not None:
        results = [a for a in results if role.lower() in a.get("role", "").lower()]
    if tag is not None:
        results = [a for a in results if tag.lower() in [t.lower() for t in a.get("tags", [])]]

    return {
        "agents": [_enrich(a) for a in results],
        "count":  len(results),
    }


@router.get("/{agent_id}", summary="Get a single agent by ID")
def get_agent(agent_id: str):
    """
    Return one agent by its catalog ID (e.g. 'backend-engineer-v1').
    Returns 404 if not found.
    """
    agent = next((a for a in AGENT_CATALOG if a["id"] == agent_id), None)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found in catalog."
        )
    return _enrich(agent)


@router.post("/select", response_model=AgentSelectResponse, summary="Record agent selection for an AEG node")
def select_agent_for_node(body: AgentSelectRequest):
    """
    Record which agent the user (or Director) selected for a given AEG node.

    In production, wire the persistence step to your Cosmos DB / Task Ledger.
    For now the endpoint validates existence and echoes back the selection.

    Body:
        {
          "aeg_node_id": "node-3",
          "agent_id":    "backend-engineer-v1"
        }
    """
    if not body.agent_id or not body.aeg_node_id:
        raise HTTPException(
            status_code=400,
            detail="Both 'agent_id' and 'aeg_node_id' are required."
        )

    agent = next((a for a in AGENT_CATALOG if a["id"] == body.agent_id), None)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{body.agent_id}' not found in catalog."
        )

    # -----------------------------------------------------------------------
    # TODO (Phase 2): persist the selection to Cosmos DB / Task Ledger
    #   cosmos_manager.save_agent_selection(body.aeg_node_id, body.agent_id)
    # -----------------------------------------------------------------------

    return AgentSelectResponse(
        status="selected",
        aeg_node_id=body.aeg_node_id,
        agent=_enrich(agent),
    )
