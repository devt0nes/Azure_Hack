from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from cosmos_client import get_cosmos_client

logger = logging.getLogger("cost_tracker")


COST_USAGE_CONTAINER = os.getenv("COSMOS_COST_USAGE_CONTAINER", "CostUsage")
COST_SUMMARY_CONTAINER = os.getenv("COSMOS_COST_SUMMARY_CONTAINER", "CostSummaries")
BUDGET_CONTAINER = os.getenv("COSMOS_BUDGET_CONTAINER", "TaskLedgers")
ESCALATIONS_CONTAINER = os.getenv("COSMOS_ESCALATION_CONTAINER", "CostEscalations")
ALERTS_CONTAINER = os.getenv("COSMOS_ALERTS_CONTAINER", "CostAlerts")

_ALERT_WEBHOOK = os.getenv("AZURE_MONITOR_ALERT_WEBHOOK_URL", "").strip()

# USD per 1K tokens defaults (override via env for your exact Azure pricing contract)
_TIER_PRICE_PER_1K: Dict[str, float] = {
    "simple": float(os.getenv("PRICE_PHI4_PER_1K_USD", "0.0018")),
    "intermediate": float(os.getenv("PRICE_GPT4O_MINI_PER_1K_USD", "0.0035")),
    "complex": float(os.getenv("PRICE_GPT4O_PER_1K_USD", "0.015")),
    "high-reasoning": float(os.getenv("PRICE_O1_PREVIEW_PER_1K_USD", "0.03")),
}


class CostTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._mem_usage: Dict[str, List[Dict[str, Any]]] = {}
        self._mem_summary: Dict[str, Dict[str, Any]] = {}
        self._mem_escalations: Dict[str, List[Dict[str, Any]]] = {}
        self._mem_alerts: Dict[str, List[Dict[str, Any]]] = {}
        self._mem_budgets: Dict[str, float] = {}
        self._cosmos = None

        conn = (os.getenv("COSMOS_CONNECTION_STR") or "").strip()
        if conn:
            try:
                self._cosmos = get_cosmos_client()
                if not self._cosmos.is_connected():
                    self._cosmos.connect()
            except Exception as exc:
                logger.warning("CostTracker falling back to in-memory store (Cosmos unavailable): %s", exc)
                self._cosmos = None

    def ensure_containers(self) -> None:
        if not self._cosmos:
            return
        try:
            self._cosmos.create_container(COST_USAGE_CONTAINER, partition_key="/project_id")
            self._cosmos.create_container(COST_SUMMARY_CONTAINER, partition_key="/project_id")
            self._cosmos.create_container(ESCALATIONS_CONTAINER, partition_key="/project_id")
            self._cosmos.create_container(ALERTS_CONTAINER, partition_key="/project_id")
        except Exception as exc:
            logger.warning("Failed ensuring cost containers: %s", exc)

    def _price(self, tier: str, tokens: int) -> float:
        price_per_1k = _TIER_PRICE_PER_1K.get(tier, _TIER_PRICE_PER_1K["intermediate"])
        return (max(0, int(tokens)) / 1000.0) * price_per_1k

    def _base_summary(self, project_id: str) -> Dict[str, Any]:
        return {
            "id": f"summary:{project_id}",
            "project_id": project_id,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "total_calls": 0,
            "total_escalations": 0,
            "budget_usd": float(self._mem_budgets.get(project_id, 100.0)),
            "pct_budget_used": 0.0,
            "cap_reached": False,
            "tier_breakdown": {},
            "agent_breakdown": [],
            "alerts": [],
            "learned_overrides": {},
            "paused_agents": [],
            "updated_at": datetime.utcnow().isoformat(),
        }

    def _sync_budget_into_summary(self, summary: Dict[str, Any], project_id: str) -> None:
        budget = self.get_budget(project_id)
        summary["budget_usd"] = float(budget)
        spend = float(summary.get("total_cost_usd", 0.0))
        pct = (spend / budget * 100.0) if budget > 0 else 0.0
        summary["pct_budget_used"] = round(pct, 4)
        summary["cap_reached"] = pct >= 100.0

    def _emit_alert(self, project_id: str, alert_type: str, message: str, summary: Dict[str, Any]) -> Dict[str, Any]:
        alert = {
            "id": f"alert:{uuid.uuid4()}",
            "project_id": project_id,
            "alert_type": alert_type,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
            "total_cost_usd": summary.get("total_cost_usd", 0.0),
            "budget_usd": summary.get("budget_usd", 0.0),
            "pct_budget_used": summary.get("pct_budget_used", 0.0),
        }

        self._mem_alerts.setdefault(project_id, []).append(alert)

        if self._cosmos:
            try:
                self._cosmos.insert_document(ALERTS_CONTAINER, dict(alert))
            except Exception as exc:
                logger.warning("Failed to persist cost alert to Cosmos: %s", exc)

        if _ALERT_WEBHOOK:
            try:
                requests.post(_ALERT_WEBHOOK, json=alert, timeout=6)
            except Exception as exc:
                logger.warning("Azure Monitor alert webhook failed: %s", exc)

        return alert

    def _maybe_raise_alert(self, project_id: str, summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        pct = float(summary.get("pct_budget_used", 0.0))
        if pct >= 100:
            target = "cap_reached"
            msg = "Budget cap reached. Non-critical tasks should be halted."
        elif pct >= 90:
            target = "critical"
            msg = "Spend is above 90% of budget."
        elif pct >= 75:
            target = "warning"
            msg = "Spend is above 75% of budget."
        else:
            return None

        latest = (self._mem_alerts.get(project_id) or [])
        if latest and latest[-1].get("alert_type") == target:
            return latest[-1]
        return self._emit_alert(project_id, target, msg, summary)

    def set_budget(self, project_id: str, budget_usd: float) -> Dict[str, Any]:
        value = max(0.01, float(budget_usd))
        with self._lock:
            self._mem_budgets[project_id] = value
            summary = self._mem_summary.get(project_id) or self._base_summary(project_id)
            summary["budget_usd"] = value
            self._sync_budget_into_summary(summary, project_id)
            summary["updated_at"] = datetime.utcnow().isoformat()
            self._mem_summary[project_id] = summary

        if self._cosmos:
            try:
                # Task ledger budget cap is persisted in TaskLedgers for compatibility.
                self._cosmos.insert_document(
                    BUDGET_CONTAINER,
                    {
                        "id": f"budget:{project_id}",
                        "task_id": f"budget:{project_id}",
                        "project_id": project_id,
                        "budget_usd": value,
                        "type": "budget",
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                )
                self._cosmos.insert_document(COST_SUMMARY_CONTAINER, dict(summary))
            except Exception as exc:
                logger.warning("Failed to persist budget to Cosmos: %s", exc)

        return {
            "project_id": project_id,
            "budget_usd": value,
            "updated_at": summary["updated_at"],
        }

    def get_budget(self, project_id: str) -> float:
        if project_id in self._mem_budgets:
            return float(self._mem_budgets[project_id])

        if self._cosmos:
            try:
                docs = self._cosmos.query_documents(
                    BUDGET_CONTAINER,
                    "SELECT TOP 1 * FROM c WHERE c.project_id = @project_id AND c.type = @type ORDER BY c.updated_at DESC",
                    [
                        {"name": "@project_id", "value": project_id},
                        {"name": "@type", "value": "budget"},
                    ],
                )
                if docs:
                    budget = float(docs[0].get("budget_usd", 100.0))
                    self._mem_budgets[project_id] = budget
                    return budget
            except Exception as exc:
                logger.warning("Failed to read budget from Cosmos: %s", exc)

        return 100.0

    def record_escalation(
        self,
        *,
        project_id: str,
        agent_role: str,
        original_tier: str,
        escalated_to: str,
        task_class: str,
        reason: str,
    ) -> Dict[str, Any]:
        item = {
            "id": f"escalation:{uuid.uuid4()}",
            "project_id": project_id,
            "agent_role": agent_role,
            "original_tier": original_tier,
            "escalated_to": escalated_to,
            "task_class": task_class,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        }

        with self._lock:
            self._mem_escalations.setdefault(project_id, []).append(item)
            summary = self._mem_summary.get(project_id) or self._base_summary(project_id)
            summary["total_escalations"] = int(summary.get("total_escalations", 0)) + 1
            summary["updated_at"] = datetime.utcnow().isoformat()
            self._mem_summary[project_id] = summary

        if self._cosmos:
            try:
                self._cosmos.insert_document(ESCALATIONS_CONTAINER, dict(item))
                self._cosmos.insert_document(COST_SUMMARY_CONTAINER, dict(self._mem_summary[project_id]))
            except Exception as exc:
                logger.warning("Failed to persist escalation to Cosmos: %s", exc)

        return item

    def record_usage(
        self,
        *,
        project_id: str,
        agent_role: str,
        model_tier: str,
        model_deployment: str,
        task_description: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> Dict[str, Any]:
        total_tokens = max(0, int(total_tokens))
        cost_usd = round(self._price(model_tier, total_tokens), 8)

        entry = {
            "id": f"usage:{uuid.uuid4()}",
            "project_id": project_id,
            "agent_role": agent_role,
            "model_tier": model_tier,
            "model_deployment": model_deployment,
            "task_description": task_description or "",
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
            "timestamp": datetime.utcnow().isoformat(),
        }

        with self._lock:
            usage_list = self._mem_usage.setdefault(project_id, [])
            usage_list.append(entry)

            summary = self._mem_summary.get(project_id) or self._base_summary(project_id)
            summary["total_tokens"] = int(summary.get("total_tokens", 0)) + total_tokens
            summary["total_cost_usd"] = round(float(summary.get("total_cost_usd", 0.0)) + cost_usd, 8)
            summary["total_calls"] = int(summary.get("total_calls", 0)) + 1

            tier_breakdown = dict(summary.get("tier_breakdown") or {})
            tier_info = dict(tier_breakdown.get(model_tier) or {"calls": 0, "tokens": 0, "cost_usd": 0.0})
            tier_info["calls"] = int(tier_info.get("calls", 0)) + 1
            tier_info["tokens"] = int(tier_info.get("tokens", 0)) + total_tokens
            tier_info["cost_usd"] = round(float(tier_info.get("cost_usd", 0.0)) + cost_usd, 8)
            tier_breakdown[model_tier] = tier_info
            summary["tier_breakdown"] = tier_breakdown

            by_agent: Dict[str, Dict[str, Any]] = {
                item["agent_id"]: dict(item)
                for item in summary.get("agent_breakdown", [])
                if isinstance(item, dict) and item.get("agent_id")
            }
            role = agent_role or "unknown_agent"
            agent_item = dict(by_agent.get(role) or {
                "agent_id": role,
                "agent_role": role,
                "tokens": 0,
                "cost_usd": 0.0,
                "calls": 0,
                "escalations": 0,
            })
            agent_item["tokens"] = int(agent_item.get("tokens", 0)) + total_tokens
            agent_item["cost_usd"] = round(float(agent_item.get("cost_usd", 0.0)) + cost_usd, 8)
            agent_item["calls"] = int(agent_item.get("calls", 0)) + 1
            by_agent[role] = agent_item
            summary["agent_breakdown"] = sorted(by_agent.values(), key=lambda x: float(x.get("cost_usd", 0.0)), reverse=True)

            self._sync_budget_into_summary(summary, project_id)
            latest_alert = self._maybe_raise_alert(project_id, summary)
            if latest_alert:
                alerts = list(summary.get("alerts") or [])
                alerts = (alerts + [latest_alert])[-5:]
                summary["alerts"] = alerts

            summary["updated_at"] = datetime.utcnow().isoformat()
            self._mem_summary[project_id] = summary

        if self._cosmos:
            try:
                self._cosmos.insert_document(COST_USAGE_CONTAINER, dict(entry))
                self._cosmos.insert_document(COST_SUMMARY_CONTAINER, dict(self._mem_summary[project_id]))
            except Exception as exc:
                logger.warning("Failed to persist usage summary to Cosmos: %s", exc)

        logger.info(
            "cost_usage_event project_id=%s agent_role=%s model_tier=%s tokens=%s cost_usd=%.8f",
            project_id,
            agent_role,
            model_tier,
            total_tokens,
            cost_usd,
        )

        return entry

    def should_halt_non_critical(self, *, project_id: str) -> bool:
        summary = self.get_summary(project_id)
        pct = float(summary.get("pct_budget_used", 0.0))
        return bool(summary.get("cap_reached")) or pct >= 95.0

    def get_summary(self, project_id: str) -> Dict[str, Any]:
        with self._lock:
            summary = dict(self._mem_summary.get(project_id) or self._base_summary(project_id))
            alerts = list(self._mem_alerts.get(project_id) or [])
            if alerts:
                summary["alerts"] = alerts[-5:]
            summary["updated_at"] = datetime.utcnow().isoformat()
            return summary

    def get_ticker(self, project_id: str) -> Dict[str, Any]:
        summary = self.get_summary(project_id)
        latest_alert = None
        alerts = summary.get("alerts") or []
        if alerts:
            latest_alert = alerts[-1]

        return {
            "project_id": project_id,
            "total_tokens": int(summary.get("total_tokens", 0)),
            "total_cost_usd": float(summary.get("total_cost_usd", 0.0)),
            "estimated_usd": float(summary.get("total_cost_usd", 0.0)),
            "budget_usd": float(summary.get("budget_usd", 0.0)),
            "pct_budget_used": float(summary.get("pct_budget_used", 0.0)),
            "cap_reached": bool(summary.get("cap_reached", False)),
            "latest_alert": latest_alert,
            "updated_at": summary.get("updated_at", datetime.utcnow().isoformat()),
        }

    def get_usage(self, project_id: str, limit: int = 20) -> Dict[str, Any]:
        with self._lock:
            rows = list(self._mem_usage.get(project_id) or [])[-max(1, int(limit)):]
        return {
            "project_id": project_id,
            "limit": int(limit),
            "records": rows,
            "entries": rows,
        }

    def get_escalations(self, project_id: str) -> Dict[str, Any]:
        with self._lock:
            rows = list(self._mem_escalations.get(project_id) or [])
        return {
            "project_id": project_id,
            "count": len(rows),
            "escalations": rows,
            "items": rows,
        }


_COST_TRACKER_SINGLETON: Optional[CostTracker] = None


def get_cost_tracker() -> CostTracker:
    global _COST_TRACKER_SINGLETON
    if _COST_TRACKER_SINGLETON is None:
        _COST_TRACKER_SINGLETON = CostTracker()
    return _COST_TRACKER_SINGLETON
