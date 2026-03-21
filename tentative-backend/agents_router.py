"""
agents_router.py
----------------
FastAPI router — Agent Catalog + selection persistence.

Routes:
  GET  /api/agents                          → full catalog (filters: ?tier=, ?role=, ?tag=)
  GET  /api/agents/{agent_id}               → single agent
  POST /api/agents/select                   → record selection, persist to Cosmos
  GET  /api/agents/selected/{project_id}    → return selected agents for a project

Public helpers (imported by app.py):
  seed_agent_catalog()       — call once on startup
  get_selected_agents(pid)   — returns list of role_key strings for a project
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from dotenv import load_dotenv

# ── path setup ───────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent
_REPO_ROOT   = _BACKEND_DIR.parent
_SHARED_DIR  = _REPO_ROOT / "shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
_LOCAL_SHARED = _BACKEND_DIR / "shared"
if str(_LOCAL_SHARED) not in sys.path:
    sys.path.insert(0, str(_LOCAL_SHARED))

from agent_catalog import AGENT_CATALOG, normalize_agent_document

load_dotenv(dotenv_path=_BACKEND_DIR / ".env")

logger = logging.getLogger(__name__)

# ── Cosmos setup ─────────────────────────────────────────────────────────────
from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos import exceptions as CosmosExceptions

COSMOS_CONNECTION_STR     = os.getenv("COSMOS_CONNECTION_STR")
DATABASE_NAME             = os.getenv("DATABASE_NAME", "agentic-nexus-db")
AGENT_CATALOG_CONTAINER   = "AgentCatalog"
AGENT_SELECTION_CONTAINER = "AgentSelections"


def _get_container(container_name: str, partition_key_path: str = "/agent_id"):
    if not COSMOS_CONNECTION_STR:
        return None
    try:
        client = CosmosClient.from_connection_string(COSMOS_CONNECTION_STR)
        db = client.create_database_if_not_exists(id=DATABASE_NAME)
        return db.create_container_if_not_exists(
            id=container_name,
            partition_key=PartitionKey(path=partition_key_path),
        )
    except Exception as e:
        logger.warning(f"⚠️  Cosmos container '{container_name}' unavailable: {e}")
        return None


# ── Seed ─────────────────────────────────────────────────────────────────────
def seed_agent_catalog():
    """
    Upserts all AGENT_CATALOG entries into Cosmos DB AgentCatalog container.
    Safe to call multiple times (idempotent). Called from app.py startup_event().
    """
    container = _get_container(AGENT_CATALOG_CONTAINER, "/agent_id")
    if container is None:
        logger.warning("⚠️  Skipping AgentCatalog seed — Cosmos DB unavailable.")
        return
    seeded = 0
    for agent in AGENT_CATALOG:
        try:
            container.upsert_item(agent)
            seeded += 1
        except Exception as e:
            logger.warning(f"⚠️  Could not seed agent {agent['agent_id']}: {e}")
    logger.info(f"✅ AgentCatalog seeded: {seeded}/{len(AGENT_CATALOG)} agents")


# ── Public helper used by app.py / main.py ───────────────────────────────────
def get_selected_agents(project_id: str) -> List[str]:
    """
    Returns list of role_key strings the user selected for this project
    e.g. ['backend_engineer', 'frontend_engineer', 'qa_engineer']
    Returns [] if none selected — caller falls back to Director AI.
    """
    container = _get_container(AGENT_SELECTION_CONTAINER, "/project_id")
    if container is None:
        return []
    try:
        query = (
            "SELECT c.role_key FROM c "
            "WHERE c.project_id = @pid AND c.type = 'agent_selection'"
        )
        items = list(container.query_items(
            query=query,
            parameters=[{"name": "@pid", "value": project_id}],
            enable_cross_partition_query=True,
        ))
        return [item["role_key"] for item in items if item.get("role_key")]
    except Exception as e:
        logger.warning(f"⚠️  Could not read AgentSelections for {project_id}: {e}")
        return []


# ── Router ───────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/agents", tags=["Agent Library"])


class AgentSelectRequest(BaseModel):
    aeg_node_id: str
    agent_id:    str
    project_id:  Optional[str] = None


class AgentSelectResponse(BaseModel):
    status:      str
    aeg_node_id: str
    agent:       dict


class AgentDeselectResponse(BaseModel):
    status: str
    agent_id: str
    project_id: str


MODEL_TIER_LABELS = {
    "simple":         "Phi-4",
    "intermediate":   "GPT-4o-mini",
    "complex":        "GPT-4o",
    "high-reasoning": "GPT-4o + o1-preview",
}
TIER_LABELS = {1: "Module Agent", 2: "Support Agent"}
BUILTIN_AGENT_IDS = {agent["agent_id"] for agent in AGENT_CATALOG}


def _enrich(agent: dict) -> dict:
    agent = normalize_agent_document(agent)
    return {
        **agent,
        "model_label": MODEL_TIER_LABELS.get(agent.get("model_tier", ""), agent.get("model_tier", "")),
        "tier_label":  TIER_LABELS.get(agent.get("tier", 0), "Agent"),
    }


def _read_catalog() -> List[dict]:
    container = _get_container(AGENT_CATALOG_CONTAINER, "/agent_id")
    if container is None:
        return []
    try:
        # Only return actual agent docs, not selection_event audit records
        items = list(container.read_all_items())
        normalized_items = [normalize_agent_document(i) for i in items if i.get("type") == "agent_catalog_entry"]
        return [
            item for item in normalized_items
            if item.get("custom") or item.get("agent_id") in BUILTIN_AGENT_IDS
        ]
    except Exception as e:
        logger.warning(f"⚠️  Could not read AgentCatalog: {e}")
        return []


def _find_static_agent(agent_id: str) -> Optional[dict]:
    for agent in AGENT_CATALOG:
        if agent.get("agent_id") == agent_id or agent.get("id") == agent_id:
            return agent
    return None


def _selection_snapshot(agent: dict) -> dict:
    agent = normalize_agent_document(agent)
    return {
        "agent_id": agent["agent_id"],
        "role": agent["role"],
        "role_key": agent["role_key"],
        "tier": agent["tier"],
        "custom": agent["custom"],
        "source": agent["source"],
        "model_tier": agent["model_tier"],
    }


def _get_agent_by_id(agent_id: str) -> Optional[dict]:
    catalog_container = _get_container(AGENT_CATALOG_CONTAINER, "/agent_id")
    if catalog_container:
        try:
            return normalize_agent_document(
                catalog_container.read_item(item=agent_id, partition_key=agent_id)
            )
        except Exception:
            pass
    agent = _find_static_agent(agent_id)
    return normalize_agent_document(agent) if agent else None


@router.get("", summary="List all agents")
def list_agents(
    tier: Optional[int] = Query(None),
    role: Optional[str] = Query(None),
    tag:  Optional[str] = Query(None),
):
    cosmos_results = _read_catalog()
    if cosmos_results:
        # Deduplicate by agent_id — keeps first occurrence only
        seen = set()
        unique = []
        for a in cosmos_results:
            key = a.get("agent_id") or a.get("id")
            if key and key not in seen:
                seen.add(key)
                unique.append(a)
        results = unique
        source = "cosmos"
    else:
        results = AGENT_CATALOG
        source = "static"

    if tier is not None:
        results = [a for a in results if a.get("tier") == tier]
    if role is not None:
        results = [a for a in results if role.lower() in a.get("role", "").lower()]
    if tag is not None:
        results = [a for a in results if tag.lower() in [t.lower() for t in a.get("tags", [])]]

    return {"agents": [_enrich(a) for a in results], "count": len(results), "source": source}


@router.get("/selected/{project_id}", summary="Get selected agents for a project")
def get_selected_for_project(project_id: str):
    role_keys = get_selected_agents(project_id)
    if not role_keys:
        return {"project_id": project_id, "selected_agents": [], "count": 0}
    catalog = _read_catalog() or AGENT_CATALOG
    matched = [a for a in catalog if a.get("role_key") in role_keys]
    return {"project_id": project_id, "selected_agents": [_enrich(a) for a in matched], "count": len(matched)}


@router.get("/{agent_id}", summary="Get a single agent by ID")
def get_agent(agent_id: str):
    container = _get_container(AGENT_CATALOG_CONTAINER, "/agent_id")
    if container:
        try:
            return _enrich(container.read_item(item=agent_id, partition_key=agent_id))
        except CosmosExceptions.CosmosResourceNotFoundError:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
        except Exception:
            pass
    agent = _find_static_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return _enrich(agent)


@router.post("/select", response_model=AgentSelectResponse, summary="Select agent for project")
def select_agent_for_node(body: AgentSelectRequest):
    """
    Persists the user's marketplace selection.
    1. Updates AgentCatalog doc (status, last_used, added_to_projects)
    2. Writes a selection record to AgentSelections (read back by main.py)
    """
    if not body.agent_id or not body.aeg_node_id:
        raise HTTPException(status_code=400, detail="agent_id and aeg_node_id are required.")

    now = datetime.now(timezone.utc).isoformat()

    # Resolve agent
    catalog_container = _get_container(AGENT_CATALOG_CONTAINER, "/agent_id")
    agent = _get_agent_by_id(body.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{body.agent_id}' not found.")

    # Update AgentCatalog doc
    if catalog_container:
        try:
            added = agent.get("added_to_projects", [])
            if body.project_id and body.project_id not in added:
                added = added + [body.project_id]
            updated = {
                **agent,
                "status": "in_use",
                "last_used": now,
                "updated_at": now,
                "added_to_projects": added,
            }
            catalog_container.upsert_item(updated)
            agent = updated
        except Exception as e:
            logger.warning(f"⚠️  Could not update AgentCatalog for {body.agent_id}: {e}")

    # Write selection record
    if body.project_id:
        sel_container = _get_container(AGENT_SELECTION_CONTAINER, "/project_id")
        if sel_container:
            try:
                sel_container.upsert_item({
                    "id":          f"{body.project_id}_{body.agent_id}",
                    "type":        "agent_selection",
                    "project_id":  body.project_id,
                    "agent_id":    body.agent_id,
                    "role_key":    agent.get("role_key", ""),
                    "role":        agent.get("role", ""),
                    "tier":        agent.get("tier"),
                    "custom":      agent.get("custom", False),
                    "source":      agent.get("source", "builtin"),
                    "model_tier":  agent.get("model_tier"),
                    "aeg_node_id": body.aeg_node_id,
                    "selected_at": now,
                    "agent_snapshot": _selection_snapshot(agent),
                })
                logger.info(f"✅ Selection persisted: {body.agent_id} → project {body.project_id}")
            except Exception as e:
                logger.warning(f"⚠️  Could not persist selection: {e}")

    return AgentSelectResponse(status="selected", aeg_node_id=body.aeg_node_id, agent=_enrich(agent))


@router.delete("/select/{project_id}/{agent_id}", response_model=AgentDeselectResponse, summary="Deselect agent for project")
def deselect_agent_for_project(project_id: str, agent_id: str):
    if not project_id or not agent_id:
        raise HTTPException(status_code=400, detail="project_id and agent_id are required.")

    sel_container = _get_container(AGENT_SELECTION_CONTAINER, "/project_id")
    if sel_container is None:
        raise HTTPException(status_code=503, detail="Agent selection storage is unavailable.")

    selection_doc_id = f"{project_id}_{agent_id}"
    try:
        sel_container.delete_item(item=selection_doc_id, partition_key=project_id)
    except CosmosExceptions.CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail=f"Selection for agent '{agent_id}' was not found in project '{project_id}'.")
    except Exception as e:
        logger.warning(f"⚠️  Could not delete selection {selection_doc_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to deselect agent.")

    catalog_container = _get_container(AGENT_CATALOG_CONTAINER, "/agent_id")
    if catalog_container:
        try:
            agent = _get_agent_by_id(agent_id)
            if agent:
                remaining_projects = [pid for pid in agent.get("added_to_projects", []) if pid != project_id]
                updated = {
                    **agent,
                    "added_to_projects": remaining_projects,
                    "status": "in_use" if remaining_projects else "available",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                catalog_container.upsert_item(updated)
        except Exception as e:
            logger.warning(f"⚠️  Could not update AgentCatalog during deselection for {agent_id}: {e}")

    logger.info(f"✅ Selection removed: {agent_id} from project {project_id}")
    return AgentDeselectResponse(status="deselected", agent_id=agent_id, project_id=project_id)
