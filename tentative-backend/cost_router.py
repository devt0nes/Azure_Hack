"""
cost_router.py
--------------
FastAPI router exposing the Cost Optimizer to the frontend.

Mount in app.py with:
    from cost_router import router as cost_router
    app.include_router(cost_router)

Routes:
    GET  /api/cost/ticker           → lightweight live ticker (polled every 3s)
    GET  /api/cost/summary          → full breakdown for the dashboard panel
    GET  /api/cost/usage            → recent per-call usage log
    GET  /api/cost/escalations      → escalation history
    GET  /api/cost/alerts           → all fired alerts
    POST /api/cost/budget           → update the budget cap
    POST /api/cost/reset/{project_id} → reset optimizer for a project (dev use)
"""

import os
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cost_optimizer import get_optimizer, list_optimizers, CostOptimizer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cost", tags=["Cost Optimizer"])

# Default budget — reads from .env, falls back to $5
_DEFAULT_BUDGET = float(os.getenv("PROJECT_BUDGET_USD", "5.0"))


# ─── Helper ──────────────────────────────────────────────────────────────────

def _get_or_404(project_id: str) -> CostOptimizer:
    optimizers = list_optimizers()
    if project_id not in optimizers:
        saved_budget = _DEFAULT_BUDGET
        try:
            import json
            from pathlib import Path
            db_path = Path(__file__).parent / "projects_db.json"
            if db_path.exists():
                data = json.loads(db_path.read_text())
                project = data.get(project_id, {})
                if "budget_usd" in project:
                    saved_budget = float(project["budget_usd"])
        except Exception as e:
            logger.warning(f"Could not read budget from projects_db: {e}")
        return get_optimizer(project_id, budget_usd=saved_budget)
    return optimizers[project_id]

# ─── Request models ──────────────────────────────────────────────────────────

class SetBudgetRequest(BaseModel):
    budget_usd: float = Field(..., gt=0, description="New budget cap in USD")


class RecordUsageRequest(BaseModel):
    """
    Allows app.py / external callers to record usage when main.py
    isn't doing it inline (e.g. during testing or replay).
    """
    project_id:        str
    agent_id:          str
    agent_role:        str
    task_description:  str
    model_tier:        str   # "simple" | "intermediate" | "complex" | "high-reasoning"
    prompt_tokens:     int
    completion_tokens: int
    attempt_number:    int = 1
    escalated_from:    Optional[str] = None


class ClassifyRequest(BaseModel):
    task_description: str
    agent_role:       str = ""


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/ticker", summary="Live cost ticker — poll every 3s")
def get_ticker(project_id: str):
    """
    Lightweight payload for the CostTicker component.
    Returns total tokens, cost, budget, % used, and latest alert.
    """
    optimizer = _get_or_404(project_id)
    return optimizer.get_live_ticker()


@router.get("/summary", summary="Full cost breakdown for the dashboard panel")
def get_summary(project_id: str):
    """
    Returns the full cost summary:
    - Global totals
    - Per-agent breakdown
    - Per-model-tier breakdown
    - All alerts
    - Learned heuristic overrides
    - Paused agents list
    """
    optimizer = _get_or_404(project_id)
    return optimizer.get_summary()


@router.get("/usage", summary="Recent per-call usage log")
def get_usage(project_id: str, limit: int = 20):
    """
    Returns the last N model calls with token counts, cost, tier, and
    escalation info. Used by the usage log table in the frontend panel.
    """
    optimizer = _get_or_404(project_id)
    return {
        "project_id": project_id,
        "records":    optimizer.get_recent_usage(limit),
        "total":      len(optimizer.usage_records),
    }


@router.get("/escalations", summary="Escalation history")
def get_escalations(project_id: str):
    """
    Returns all escalation events — which task classes triggered
    model upgrades and what they escalated to.
    """
    optimizer = _get_or_404(project_id)
    return {
        "project_id":  project_id,
        "escalations": optimizer.get_escalations(),
        "learned_overrides": {
            k: v.value for k, v in optimizer._learned_tier_overrides.items()
        },
    }


@router.get("/alerts", summary="All fired budget alerts")
def get_alerts(project_id: str):
    """
    Returns warning / critical / cap_reached alerts in order.
    """
    optimizer = _get_or_404(project_id)
    return {
        "project_id": project_id,
        "alerts":     [optimizer._alert_to_dict(a) for a in optimizer.alerts],
        "count":      len(optimizer.alerts),
    }


@router.post("/budget", summary="Update the budget cap")
def set_budget(project_id: str, request: SetBudgetRequest):
    """
    Update the budget cap for a project at runtime.
    Resets the cap_reached flag so paused agents can resume.
    Persists the new budget to projects_db.json so it survives restarts.
    """
    optimizer = _get_or_404(project_id)
    old_budget = optimizer.budget_usd
    optimizer.set_budget(request.budget_usd)

    # ── Persist budget to projects_db so it survives backend restarts ────────
    try:
        from app import project_manager
        project = project_manager.get_project(project_id)
        if project:
            project["budget_usd"] = request.budget_usd
            project_manager._save_projects()
    except Exception as e:
        logger.warning(f"⚠️  Could not persist budget to projects_db: {e}")

    logger.info(
        f"💰 Budget updated for {project_id}: "
        f"${old_budget:.2f} → ${request.budget_usd:.2f}"
    )

    return {
        "project_id":  project_id,
        "old_budget":  old_budget,
        "new_budget":  request.budget_usd,
        "cap_reached": optimizer.cap_reached,
        "message":     "Budget updated. Paused agents may now resume.",
    }


@router.post("/classify", summary="Classify a task description into a complexity tier")
def classify_task(project_id: str, request: ClassifyRequest):
    """
    Utility endpoint — returns which model tier would be selected for
    a given task description. Useful for debugging and the frontend
    'model preview' feature.
    """
    optimizer = _get_or_404(project_id)
    tier = optimizer.classify_task(request.task_description, request.agent_role)
    model = optimizer.get_model_for_tier(tier)
    return {
        "task_description": request.task_description,
        "agent_role":       request.agent_role,
        "complexity_tier":  tier.value,
        "model_deployment": model,
    }


@router.post("/usage/record", summary="Manually record a model call's usage")
def record_usage(request: RecordUsageRequest):
    """
    Allows external callers (e.g. app.py background tasks) to record
    token usage when the optimizer isn't wired inline.
    """
    from cost_optimizer import ModelTier as MT
    try:
        tier = MT(request.model_tier)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model_tier '{request.model_tier}'. "
                   f"Must be one of: simple, intermediate, complex, high-reasoning"
        )

    escalated_from = None
    if request.escalated_from:
        try:
            escalated_from = MT(request.escalated_from)
        except ValueError:
            pass

    optimizer = get_optimizer(request.project_id)
    record = optimizer.record_usage(
        agent_id=request.agent_id,
        agent_role=request.agent_role,
        task_description=request.task_description,
        model_tier=tier,
        prompt_tokens=request.prompt_tokens,
        completion_tokens=request.completion_tokens,
        attempt_number=request.attempt_number,
        escalated_from=escalated_from,
    )

    return {
        "status":     "recorded",
        "cost_usd":   round(record.cost_usd, 6),
        "total_cost": round(optimizer.total_cost, 6),
    }


@router.delete("/reset/{project_id}", summary="Reset optimizer for a project")
def reset_optimizer(project_id: str):
    """
    Clears all usage records and resets totals for a project.
    Useful during development / testing.
    """
    optimizers = list_optimizers()
    if project_id in optimizers:
        opt = optimizers[project_id]
        budget = opt.budget_usd
        opt.delete_persisted_state()
        # Re-create fresh
        from cost_optimizer import _optimizers, CostOptimizer
        _optimizers[project_id] = CostOptimizer(project_id, budget)
        return {"status": "reset", "project_id": project_id}

    return {"status": "not_found", "project_id": project_id}
