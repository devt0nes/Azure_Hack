"""
agents_router.py
----------------
FastAPI router — Agent Catalog + selection persistence + Reputation Scoring.

Routes:
  GET  /api/agents                              → full catalog (filters: ?tier=, ?role=, ?tag=)
  GET  /api/agents/{agent_id}                   → single agent (enriched with live reputation)
  GET  /api/agents/{agent_id}/score             → reputation score breakdown
  POST /api/agents/select                       → record selection, persist to Cosmos
  GET  /api/agents/selected/{project_id}        → return selected agents for a project
  DELETE /api/agents/select/{project_id}/{agent_id} → deselect agent
  POST /api/agents/{agent_id}/report            → file a community report
  POST /api/agents/{agent_id}/audit             → resolve audit (restore / retire)
  POST /api/agents/{agent_id}/engagement        → record one agent engagement (called by orchestrator)

Public helpers (imported by app.py / main.py):
  seed_agent_catalog()            — call once on startup (seeds catalog + reputation docs)
  get_selected_agents(pid)        — returns list of role_key strings for a project
  record_agent_engagement(metrics)— orchestrator calls after each agent run
  init_reputation_service(svc)    — inject shared ReputationService at startup
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

from agent_catalog import AGENT_CATALOG, normalize_agent_document

# ── Reputation scoring (merged from reputation-scoring service) ──────────────
from src.reputation_service import ReputationService
from src.cosmos_store import CosmosReputationStore
from src.schemas import (
    AgentReputationDocument, AgentStatus as RepAgentStatus,
    BuildComplexity, ModelTier, RawEngagementMetrics, DimensionalScores,
)

load_dotenv(dotenv_path=_BACKEND_DIR / ".env")
logger = logging.getLogger(__name__)

# ── Cosmos setup (catalog + selections) ─────────────────────────────────────
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


# ── Reputation service singleton ─────────────────────────────────────────────
_rep_svc: Optional[ReputationService] = None


def init_reputation_service(svc: ReputationService) -> None:
    """Called from app.py startup_event() to inject the shared service instance."""
    global _rep_svc
    _rep_svc = svc
    logger.info("✅ ReputationService injected into agents_router")


def _get_rep_svc() -> Optional[ReputationService]:
    """
    Returns the ReputationService if available.
    Falls back to lazy init from COSMOS_ENDPOINT / COSMOS_KEY env vars.
    All callers must handle None gracefully (service degrades, catalog still works).
    """
    global _rep_svc
    if _rep_svc is None:
        endpoint = os.getenv("COSMOS_ENDPOINT")
        key      = os.getenv("COSMOS_KEY")
        if endpoint and key:
            try:
                store    = CosmosReputationStore(endpoint, key,
                               os.getenv("COSMOS_DATABASE", "agentic_nexus"))
                _rep_svc = ReputationService(store=store)
                logger.info("✅ ReputationService lazy-initialised in agents_router")
            except Exception as e:
                logger.warning(f"⚠️  ReputationService unavailable: {e}")
    return _rep_svc


# ── Seed ─────────────────────────────────────────────────────────────────────

def seed_agent_catalog() -> None:
    """
    1. Upserts all AGENT_CATALOG entries into Cosmos DB AgentCatalog container.
    2. Seeds reputation documents for every builtin agent (idempotent).
    Safe to call multiple times. Called from app.py startup_event().
    """
    # ── Seed catalog docs ───────────────────────────────────────────────────
    container = _get_container(AGENT_CATALOG_CONTAINER, "/agent_id")
    if container is None:
        logger.warning("⚠️  Skipping AgentCatalog seed — Cosmos DB unavailable.")
    else:
        seeded = 0
        for agent in AGENT_CATALOG:
            try:
                container.upsert_item(agent)
                seeded += 1
            except Exception as e:
                logger.warning(f"⚠️  Could not seed agent {agent['agent_id']}: {e}")
        logger.info(f"✅ AgentCatalog seeded: {seeded}/{len(AGENT_CATALOG)} agents")

    # ── Seed reputation docs for builtins ────────────────────────────────────
    svc = _get_rep_svc()
    if svc is None:
        logger.warning("⚠️  Skipping reputation seed — ReputationService unavailable.")
        return
    rep_seeded = 0
    for agent in AGENT_CATALOG:
        try:
            svc.seed_builtin_agent(
                agent_id=      agent["agent_id"],
                agent_name=    agent.get("role", agent["agent_id"]),
                initial_score= agent.get("reputation_score", 0.5),
            )
            rep_seeded += 1
        except Exception as e:
            logger.warning(f"⚠️  Could not seed reputation for {agent['agent_id']}: {e}")
    logger.info(f"✅ Reputation docs seeded: {rep_seeded}/{len(AGENT_CATALOG)} agents")


# ── Public helper used by app.py / main.py ───────────────────────────────────

def get_selected_agents(project_id: str) -> List[str]:
    """
    Returns list of role_key strings the user selected for this project.
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


def record_agent_engagement(metrics: RawEngagementMetrics) -> Optional[dict]:
    """
    Called by main.py orchestrator after each agent completes its execution.
    Records the engagement, updates reputation score via EMA, runs anti-gaming checks.
    Returns a summary dict, or None if the ReputationService is unavailable.

    Usage in main.py (after agent.status == COMPLETED):
        from agents_router import record_agent_engagement, RawEngagementMetrics, BuildComplexity, ModelTier
        result = record_agent_engagement(RawEngagementMetrics(
            agent_id=agent.agent_id,
            build_id=project_id,
            owner_azure_ad_id=owner_id,
            complexity=BuildComplexity(...),
            contract_fidelity=...,
            downstream_satisfaction=...,
            pre_healer_test_pass_rate=...,
            security_compliance_score=...,
            token_efficiency=...,
        ))
    """
    svc = _get_rep_svc()
    if svc is None:
        return None
    try:
        result = svc.record_engagement(metrics)
        logger.info(
            f"📊 Reputation updated: {metrics.agent_id} "
            f"{result.old_score:.3f}→{result.new_score:.3f} "
            f"{'🚩 FLAGGED' if result.flagged else '✅'}"
        )
        return {
            "agent_id":   metrics.agent_id,
            "old_score":  result.old_score,
            "new_score":  result.new_score,
            "flagged":    result.flagged,
            "flag_reason": result.flag_reason,
            "status":     result.doc.status,
            "dimensional": result.doc.dimensional_scores.model_dump(),
        }
    except ValueError as e:
        # Agent has no reputation doc yet — seed it automatically and retry once
        logger.warning(f"⚠️  No reputation doc for {metrics.agent_id}, auto-seeding and retrying.")
        try:
            svc.seed_builtin_agent(metrics.agent_id, metrics.agent_id)
            result = svc.record_engagement(metrics)
            return {
                "agent_id":   metrics.agent_id,
                "old_score":  result.old_score,
                "new_score":  result.new_score,
                "flagged":    result.flagged,
                "flag_reason": result.flag_reason,
                "status":     result.doc.status,
                "dimensional": result.doc.dimensional_scores.model_dump(),
            }
        except Exception as retry_err:
            logger.warning(f"⚠️  Retry also failed for {metrics.agent_id}: {retry_err}")
            return None
    except Exception as e:
        logger.warning(f"⚠️  Could not record engagement for {metrics.agent_id}: {e}")
        return None


# ── Router ───────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/agents", tags=["Agent Library"])


# ── Request / Response models ─────────────────────────────────────────────────

class AgentSelectRequest(BaseModel):
    aeg_node_id: str
    agent_id:    str
    project_id:  Optional[str] = None


class AgentSelectResponse(BaseModel):
    status:      str
    aeg_node_id: str
    agent:       dict


class AgentDeselectResponse(BaseModel):
    status:     str
    agent_id:   str
    project_id: str


class ReportRequest(BaseModel):
    reporter_azure_ad_id: str
    notes:                str = ""


class AuditRequest(BaseModel):
    auditor: str
    action:  str   # "restore" | "retire"
    notes:   str = ""


class EngagementRequest(BaseModel):
    """
    Posted by the orchestrator (main.py) after each agent completes.
    All metric fields are normalised to [0, 1] before posting.
    """
    build_id:                  str
    owner_azure_ad_id:         str
    aeg_node_count:            int   = 5
    aeg_edge_count:            int   = 4
    total_tokens_consumed:     int   = 50_000
    downstream_agent_count:    int   = 2
    model_tier:                str   = "gpt4o"   # phi4 | gpt4o_mini | gpt4o | gpt4o_o1
    contract_fidelity:         float = 0.75
    downstream_satisfaction:   float = 1.0
    pre_healer_test_pass_rate: float = 0.75
    security_compliance_score: float = 0.75
    token_efficiency:          float = 0.5


# ── Helpers ───────────────────────────────────────────────────────────────────

MODEL_TIER_LABELS = {
    "simple":         "Phi-4",
    "intermediate":   "GPT-4o-mini",
    "complex":        "GPT-4o",
    "high-reasoning": "GPT-4o + o1-preview",
}
TIER_LABELS = {1: "Module Agent", 2: "Support Agent"}
BUILTIN_AGENT_IDS = {agent["agent_id"] for agent in AGENT_CATALOG}

# Maps agents_router model_tier strings → scorer ModelTier enum values
_MODEL_TIER_MAP = {
    "simple":         ModelTier.PHI4,
    "phi4":           ModelTier.PHI4,
    "intermediate":   ModelTier.GPT4O_MINI,
    "gpt4o_mini":     ModelTier.GPT4O_MINI,
    "complex":        ModelTier.GPT4O,
    "gpt4o":          ModelTier.GPT4O,
    "high-reasoning": ModelTier.GPT4O_O1,
    "gpt4o_o1":       ModelTier.GPT4O_O1,
}


def _enrich(agent: dict) -> dict:
    """
    Adds display labels + live reputation data from ReputationService.
    Falls back to catalog reputation_score if service is unavailable.
    """
    agent = normalize_agent_document(agent)
    enriched = {
        **agent,
        "model_label":    MODEL_TIER_LABELS.get(agent.get("model_tier", ""), agent.get("model_tier", "")),
        "tier_label":     TIER_LABELS.get(agent.get("tier", 0), "Agent"),
        # Defaults — overwritten below if reputation service is live
        "selection_score":   agent.get("reputation_score", 0.5),
        "reputation_status": "active",
        "dimensional_scores": None,
        "total_engagements":  0,
        "score_under_review": False,
    }

    svc = _get_rep_svc()
    if svc:
        try:
            rep_doc: Optional[AgentReputationDocument] = svc._store.get_reputation(agent["agent_id"])
            if rep_doc:
                enriched["reputation_score"]  = rep_doc.reputation_score
                enriched["selection_score"]   = svc.selection_score(rep_doc)
                enriched["reputation_status"] = rep_doc.status.value
                enriched["dimensional_scores"] = rep_doc.dimensional_scores.model_dump()
                enriched["total_engagements"] = rep_doc.total_engagements
                enriched["score_under_review"] = rep_doc.anti_gaming.score_under_review
        except Exception as e:
            logger.debug(f"Could not fetch live reputation for {agent.get('agent_id')}: {e}")

    return enriched


def _read_catalog() -> List[dict]:
    container = _get_container(AGENT_CATALOG_CONTAINER, "/agent_id")
    if container is None:
        return []
    try:
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
        "role":     agent["role"],
        "role_key": agent["role_key"],
        "tier":     agent["tier"],
        "custom":   agent["custom"],
        "source":   agent["source"],
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


# ── Routes ────────────────────────────────────────────────────────────────────
# ORDER MATTERS: specific paths before parameterised ones.

@router.get("", summary="List all agents")
def list_agents(
    tier: Optional[int] = Query(None),
    role: Optional[str] = Query(None),
    tag:  Optional[str] = Query(None),
):
    """Returns full catalog enriched with live reputation scores."""
    cosmos_results = _read_catalog()
    if cosmos_results:
        seen, unique = set(), []
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
    catalog_container = _get_container(AGENT_CATALOG_CONTAINER, "/agent_id")
    agent = _get_agent_by_id(body.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{body.agent_id}' not found.")

    if catalog_container:
        try:
            added = agent.get("added_to_projects", [])
            if body.project_id and body.project_id not in added:
                added = added + [body.project_id]
            updated = {**agent, "status": "in_use", "last_used": now,
                       "updated_at": now, "added_to_projects": added}
            catalog_container.upsert_item(updated)
            agent = updated
        except Exception as e:
            logger.warning(f"⚠️  Could not update AgentCatalog for {body.agent_id}: {e}")

    if body.project_id:
        sel_container = _get_container(AGENT_SELECTION_CONTAINER, "/project_id")
        if sel_container:
            try:
                sel_container.upsert_item({
                    "id":           f"{body.project_id}_{body.agent_id}",
                    "type":         "agent_selection",
                    "project_id":   body.project_id,
                    "agent_id":     body.agent_id,
                    "role_key":     agent.get("role_key", ""),
                    "role":         agent.get("role", ""),
                    "tier":         agent.get("tier"),
                    "custom":       agent.get("custom", False),
                    "source":       agent.get("source", "builtin"),
                    "model_tier":   agent.get("model_tier"),
                    "aeg_node_id":  body.aeg_node_id,
                    "selected_at":  now,
                    "agent_snapshot": _selection_snapshot(agent),
                })
            except Exception as e:
                logger.warning(f"⚠️  Could not persist selection: {e}")

    return AgentSelectResponse(status="selected", aeg_node_id=body.aeg_node_id, agent=_enrich(agent))


@router.delete("/select/{project_id}/{agent_id}", response_model=AgentDeselectResponse,
               summary="Deselect agent for project")
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
        raise HTTPException(status_code=404,
            detail=f"Selection for agent '{agent_id}' was not found in project '{project_id}'.")
    except Exception as e:
        logger.warning(f"⚠️  Could not delete selection {selection_doc_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to deselect agent.")

    catalog_container = _get_container(AGENT_CATALOG_CONTAINER, "/agent_id")
    if catalog_container:
        try:
            agent = _get_agent_by_id(agent_id)
            if agent:
                remaining = [pid for pid in agent.get("added_to_projects", []) if pid != project_id]
                catalog_container.upsert_item({
                    **agent,
                    "added_to_projects": remaining,
                    "status": "in_use" if remaining else "available",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
        except Exception as e:
            logger.warning(f"⚠️  Could not update AgentCatalog during deselection: {e}")

    return AgentDeselectResponse(status="deselected", agent_id=agent_id, project_id=project_id)


# ── Reputation routes (specific sub-paths before /{agent_id}) ────────────────

@router.get("/{agent_id}/score", summary="Get live reputation score for an agent")
def get_reputation_score(agent_id: str):
    """
    Returns live reputation score, selection score, dimensional breakdown,
    and anti-gaming status. Used by Director for Stage 3 catalog ranking.
    """
    svc = _get_rep_svc()
    if svc is None:
        raise HTTPException(status_code=503, detail="Reputation service unavailable.")
    try:
        doc = svc._store.get_reputation(agent_id)
    except CosmosExceptions.CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail=f"No reputation document for '{agent_id}'.")
    except Exception as e:
        logger.error(f"Error fetching reputation score for {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Reputation service unavailable.")
    if doc is None:
        raise HTTPException(status_code=404, detail=f"No reputation document for '{agent_id}'.")
    return {
        "agent_id":           agent_id,
        "reputation_score":   doc.reputation_score,
        "selection_score":    svc.selection_score(doc),
        "status":             doc.status,
        "dimensional_scores": doc.dimensional_scores.model_dump(),
        "total_engagements":  doc.total_engagements,
        "score_under_review": doc.anti_gaming.score_under_review,
        "review_reason":      doc.anti_gaming.review_reason,
    }


@router.post("/{agent_id}/report", status_code=201, summary="File a community report")
def report_agent(agent_id: str, body: ReportRequest):
    """
    Command Center UI calls this when a user flags unexpected agent behaviour.
    Three independent reports within 30 days → auto-suspend.
    """
    svc = _get_rep_svc()
    if svc is None:
        raise HTTPException(status_code=503, detail="Reputation service unavailable.")
    try:
        result = svc.file_community_report(agent_id, body.reporter_azure_ad_id, body.notes)
        return {
            "accepted":        result.accepted,
            "total_in_window": result.total_in_window,
            "auto_suspended":  result.auto_suspended,
            "message":         result.message,
        }
    except CosmosExceptions.CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail=f"No reputation document for '{agent_id}'.")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error filing report for {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Reputation service unavailable.")


@router.post("/{agent_id}/audit", summary="Resolve audit: restore or retire agent")
def audit_agent(agent_id: str, body: AuditRequest):
    """Human reviewers call this to clear a false positive or permanently retire an agent."""
    if body.action not in ("restore", "retire"):
        raise HTTPException(status_code=400, detail="action must be 'restore' or 'retire'.")
    svc = _get_rep_svc()
    if svc is None:
        raise HTTPException(status_code=503, detail="Reputation service unavailable.")
    try:
        doc = svc.resolve_audit(agent_id, body.auditor, body.action, body.notes)
        return {
            "agent_id": agent_id,
            "status":   doc.status,
            "message":  f"Agent {body.action}d by {body.auditor}.",
        }
    except CosmosExceptions.CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail=f"No reputation document for '{agent_id}'.")
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error resolving audit for {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Reputation service unavailable.")


@router.post("/{agent_id}/engagement", status_code=201,
             summary="Record agent engagement (called by orchestrator)")
def post_engagement(agent_id: str, body: EngagementRequest):
    """
    Orchestrator (main.py) calls this endpoint — or uses record_agent_engagement()
    directly — after each agent completes its execution in a build.
    """
    tier = _MODEL_TIER_MAP.get(body.model_tier, ModelTier.GPT4O)
    try:
        complexity = BuildComplexity(
            aeg_node_count=        body.aeg_node_count,
            aeg_edge_count=        body.aeg_edge_count,
            total_tokens_consumed= body.total_tokens_consumed,
            downstream_agent_count=body.downstream_agent_count,
            model_tier=            tier,
        )
        metrics = RawEngagementMetrics(
            agent_id=                  agent_id,
            build_id=                  body.build_id,
            owner_azure_ad_id=         body.owner_azure_ad_id,
            complexity=                complexity,
            contract_fidelity=         body.contract_fidelity,
            downstream_satisfaction=   body.downstream_satisfaction,
            pre_healer_test_pass_rate= body.pre_healer_test_pass_rate,
            security_compliance_score= body.security_compliance_score,
            token_efficiency=          body.token_efficiency,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid engagement metrics: {e}")

    result = record_agent_engagement(metrics)
    if result is None:
        raise HTTPException(status_code=503, detail="Reputation service unavailable.")
    return result


# ── Single agent (parameterised — must come last) ────────────────────────────

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