"""
cost_optimizer.py
-----------------
Token-Thrifty Cost Optimizer — The Budget Cape (Section 5.2)

Responsibilities:
  1. Task complexity classification  → selects cheapest capable model
  2. Model Escalation Policy         → auto-upgrades on failure (4-tier ladder)
  3. Token tracking per agent        → per-call and cumulative
  4. Budget cap enforcement          → halts non-critical tasks near cap
  5. Cost alert emission             → fires when spend trends above budget
  6. Escalation heuristic learning   → updates complexity map when a task
                                       class consistently escalates

Design note: this is a ROUTING LAYER, not an agent. Every model call in
main.py is wrapped by CostOptimizer.route_call(). The optimizer is
instantiated once per project and passed into the SwarmOrchestrator /
Agent instances.
"""

import os
import re
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass

from azure.cosmos import CosmosClient
from azure.cosmos import exceptions as CosmosExceptions

logger = logging.getLogger(__name__)


# ─── Model tiers (cheapest → most capable) ──────────────────────────────────

class ModelTier(str, Enum):
    SIMPLE        = "simple"           # Phi-4
    INTERMEDIATE  = "intermediate"     # GPT-4o-mini
    COMPLEX       = "complex"          # GPT-4o
    HIGH_REASONING= "high-reasoning"   # GPT-4o + o1-preview


# Maps tier → actual Azure OpenAI deployment name
# Override with env vars if your deployment names differ
MODEL_DEPLOYMENT_MAP: Dict[ModelTier, str] = {
    ModelTier.SIMPLE:         os.getenv("MODEL_SIMPLE",         "phi-4"),
    ModelTier.INTERMEDIATE:   os.getenv("MODEL_INTERMEDIATE",   "gpt-4o-mini"),
    ModelTier.COMPLEX:        os.getenv("MODEL_COMPLEX",        "gpt-4o"),
    ModelTier.HIGH_REASONING: os.getenv("MODEL_HIGH_REASONING", "gpt-4o"),   # same deployment, higher temp/reasoning
}

# Pricing per 1K tokens (input + output averaged) in USD
# Adjust to match your Azure agreement
MODEL_COST_PER_1K: Dict[ModelTier, float] = {
    ModelTier.SIMPLE:         0.0001,   # Phi-4
    ModelTier.INTERMEDIATE:   0.0003,   # GPT-4o-mini
    ModelTier.COMPLEX:        0.005,    # GPT-4o
    ModelTier.HIGH_REASONING: 0.015,    # GPT-4o + o1-preview
}

# Escalation ladder: attempt index → tier
ESCALATION_LADDER: List[ModelTier] = [
    ModelTier.SIMPLE,           # attempt 1
    ModelTier.INTERMEDIATE,     # attempt 2
    ModelTier.COMPLEX,          # attempt 3
    ModelTier.HIGH_REASONING,   # attempt 4
]

# Healer Agent always dispatched at this tier minimum (Section 5.2)
HEALER_MINIMUM_TIER = ModelTier.COMPLEX

COSMOS_CONNECTION_STR = os.getenv("COSMOS_CONNECTION_STR")
DATABASE_NAME = os.getenv("DATABASE_NAME", "agentic-nexus-db")
COST_STATE_CONTAINER = os.getenv("COST_STATE_CONTAINER", "CostOptimizerState")
ENABLE_COST_STATE_PERSISTENCE = os.getenv("ENABLE_COST_STATE_PERSISTENCE", "false").strip().lower() == "true"


# ─── Complexity keyword heuristic ───────────────────────────────────────────
# Maps task description keywords → complexity tier
# The Director scores a task against these lists and picks the highest match.

COMPLEXITY_KEYWORDS: Dict[ModelTier, List[str]] = {
    ModelTier.SIMPLE: [
        "docstring", "comment", "readme", "css", "style", "boilerplate",
        "rename", "format", "indent", "whitespace", "changelog", "typo",
        "documentation", "log message", "placeholder", "static", "config",
        "env variable", "gitignore", "license",
    ],
    ModelTier.INTERMEDIATE: [
        "crud", "endpoint", "route", "controller", "unit test", "config file",
        "migration", "model", "serializer", "validator", "helper", "utility",
        "schema", "form", "component", "hook", "service", "repository",
        "dto", "interface", "type", "enum",
    ],
    ModelTier.COMPLEX: [
        "auth", "authentication", "authorization", "oauth", "jwt", "security",
        "architecture", "data model", "database design", "indexing strategy",
        "performance", "optimise", "optimize", "refactor", "integration",
        "api design", "openapi", "microservice", "multi-tenant", "encryption",
        "access control", "iam", "owasp", "threat model",
    ],
    ModelTier.HIGH_REASONING: [
        "plan", "planning", "feasibility", "root cause", "debug", "diagnose",
        "orchestrate", "orchestration", "director", "strategy", "architect",
        "decompose", "agent graph", "aeg", "dependency graph", "conflict",
        "healer", "patch analysis", "cascade", "cross-cutting",
    ],
}


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class TokenUsageRecord:
    """One model call's worth of token data."""
    agent_id:        str
    agent_role:      str
    task_description:str
    model_tier:      ModelTier
    model_deployment:str
    prompt_tokens:   int
    completion_tokens:int
    total_tokens:    int
    cost_usd:        float
    timestamp:       str
    attempt_number:  int        # 1-4 (escalation attempt)
    escalated_from:  Optional[ModelTier] = None
    project_id:      Optional[str] = None


@dataclass
class EscalationRecord:
    """Tracks a single escalation event for heuristic learning."""
    task_class:        str          # normalised task description stem
    original_tier:     ModelTier
    escalated_to:      ModelTier
    reason:            str
    timestamp:         str
    agent_role:        str


@dataclass
class CostAlert:
    """Fired when spend crosses a threshold."""
    alert_type:    str          # "warning" | "critical" | "cap_reached"
    message:       str
    spend_usd:     float
    budget_usd:    float
    pct_used:      float
    timestamp:     str
    project_id:    Optional[str] = None


# ─── Main optimizer class ────────────────────────────────────────────────────

class CostOptimizer:
    """
    Wraps every model call. Instantiate once per project session and pass
    into agents so they call self.cost_optimizer.route_call(...) instead of
    hitting the OpenAI client directly.
    """

    def __init__(
        self,
        project_id: str,
        budget_usd: float = 5.0,         # default $5 budget per project
        warning_threshold: float = 0.75,  # alert at 75% of budget
        critical_threshold: float = 0.90, # alert at 90% of budget
    ):
        self.project_id          = project_id
        self.budget_usd          = budget_usd
        self.warning_threshold   = warning_threshold
        self.critical_threshold  = critical_threshold
        self._state_enabled      = bool(COSMOS_CONNECTION_STR) and ENABLE_COST_STATE_PERSISTENCE
        self.state_container     = self._init_state_container()

        # Token / cost tracking
        self.usage_records: List[TokenUsageRecord]   = []
        self.escalation_records: List[EscalationRecord] = []
        self.alerts: List[CostAlert]                 = []

        # Per-agent cumulative spend: agent_id → {tokens, cost}
        self.agent_spend: Dict[str, Dict] = {}

        # Running totals
        self.total_tokens: int   = 0
        self.total_cost:   float = 0.0

        # Heuristic learning: task_class → escalation count
        self._escalation_counts: Dict[str, int] = {}
        # Overrides learned from history: task_class → upgraded tier
        self._learned_tier_overrides: Dict[str, ModelTier] = {}

        # Budget enforcement state
        self.cap_reached:    bool = False
        self.paused_agents:  List[str] = []

        self._load_persisted_state()

        logger.info(
            f"💰 CostOptimizer initialised | project={project_id} | "
            f"budget=${budget_usd:.2f}"
        )

    # ── 1. Complexity classification ────────────────────────────────────────

    def classify_task(self, task_description: str, agent_role: str = "") -> ModelTier:
        """
        Classify a task description into a complexity tier using keyword
        heuristics. Returns the cheapest tier that covers the task.

        Priority: HIGH_REASONING > COMPLEX > INTERMEDIATE > SIMPLE
        The first (highest) tier whose keywords match wins.
        """
        text = (task_description + " " + agent_role).lower()

        # Check learned overrides first
        task_stem = self._stem_task(task_description)
        if task_stem in self._learned_tier_overrides:
            override = self._learned_tier_overrides[task_stem]
            logger.info(
                f"🧠 [CostOptimizer] Learned override: '{task_stem}' → {override.value}"
            )
            return override

        # Keyword heuristic (highest tier wins)
        for tier in reversed(ESCALATION_LADDER):   # HIGH_REASONING first
            keywords = COMPLEXITY_KEYWORDS.get(tier, [])
            if any(kw in text for kw in keywords):
                logger.info(
                    f"📊 [CostOptimizer] Classified '{task_description[:50]}' "
                    f"→ {tier.value}"
                )
                return tier

        # Default: intermediate (safe middle ground)
        logger.info(
            f"📊 [CostOptimizer] No keyword match for '{task_description[:50]}' "
            f"→ defaulting to intermediate"
        )
        return ModelTier.INTERMEDIATE

    def get_model_for_tier(self, tier: ModelTier) -> str:
        """Return the deployment name for a given tier."""
        return MODEL_DEPLOYMENT_MAP[tier]

    # ── 2. Token tracking ────────────────────────────────────────────────────

    def record_usage(
        self,
        agent_id:          str,
        agent_role:        str,
        task_description:  str,
        model_tier:        ModelTier,
        prompt_tokens:     int,
        completion_tokens: int,
        attempt_number:    int = 1,
        escalated_from:    Optional[ModelTier] = None,
    ) -> TokenUsageRecord:
        """
        Record token consumption after a model call completes.
        Updates all running totals and checks budget thresholds.
        """
        total_tokens = prompt_tokens + completion_tokens
        cost_usd     = (total_tokens / 1000) * MODEL_COST_PER_1K[model_tier]

        record = TokenUsageRecord(
            agent_id=agent_id,
            agent_role=agent_role,
            task_description=task_description,
            model_tier=model_tier,
            model_deployment=MODEL_DEPLOYMENT_MAP[model_tier],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            timestamp=datetime.now(timezone.utc).isoformat(),
            attempt_number=attempt_number,
            escalated_from=escalated_from,
            project_id=self.project_id,
        )

        self.usage_records.append(record)

        # Update per-agent spend
        if agent_id not in self.agent_spend:
            self.agent_spend[agent_id] = {
                "agent_id":   agent_id,
                "agent_role": agent_role,
                "tokens":     0,
                "cost_usd":   0.0,
                "call_count": 0,
                "escalations":0,
            }
        self.agent_spend[agent_id]["tokens"]     += total_tokens
        self.agent_spend[agent_id]["cost_usd"]   += cost_usd
        self.agent_spend[agent_id]["call_count"] += 1
        if escalated_from:
            self.agent_spend[agent_id]["escalations"] += 1

        # Update global totals
        self.total_tokens += total_tokens
        self.total_cost   += cost_usd

        logger.info(
            f"💵 [{agent_id}] {model_tier.value} | "
            f"{total_tokens} tokens | ${cost_usd:.4f} | "
            f"total=${self.total_cost:.4f}"
        )

        # Check budget thresholds
        self._check_budget_thresholds()
        self._persist_state()

        return record

    # ── 3. Model Escalation Policy ───────────────────────────────────────────

    def get_escalation_tier(
        self,
        current_tier: ModelTier,
        attempt_number: int,
        agent_role: str = "",
        task_description: str = "",
    ) -> Optional[ModelTier]:
        """
        Return the next tier in the escalation ladder, or None if already
        at the top. Records the escalation for heuristic learning.

        attempt_number: the attempt that FAILED (1-based).
        Returns the tier to use for the NEXT attempt.
        """
        # Healer agents always start at COMPLEX minimum
        if "healer" in agent_role.lower():
            if current_tier in (ModelTier.SIMPLE, ModelTier.INTERMEDIATE):
                logger.info(
                    f"🔺 [CostOptimizer] Healer override: "
                    f"{current_tier.value} → {HEALER_MINIMUM_TIER.value}"
                )
                return HEALER_MINIMUM_TIER

        # Guard: if current_tier isn't on the standard ladder (e.g. custom),
        # find its position or default to index 0
        try:
            current_index = ESCALATION_LADDER.index(current_tier)
        except ValueError:
            current_index = 0

        next_index = current_index + 1  # always move exactly one rung up
        if next_index >= len(ESCALATION_LADDER):
            logger.warning(
                f"⚠️  [CostOptimizer] Max escalation reached for "
                f"'{task_description[:40]}' after {attempt_number} attempts"
            )
            return None

        next_tier = ESCALATION_LADDER[next_index]

        # Record escalation
        esc = EscalationRecord(
            task_class=self._stem_task(task_description),
            original_tier=current_tier,
            escalated_to=next_tier,
            reason=f"Failed self-validation on attempt {attempt_number}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent_role=agent_role,
        )
        self.escalation_records.append(esc)

        # Update heuristic learning counts
        self._update_escalation_heuristic(esc)

        logger.info(
            f"🔺 [CostOptimizer] Escalating '{task_description[:40]}': "
            f"{current_tier.value} → {next_tier.value} "
            f"(attempt {attempt_number + 1})"
        )
        self._persist_state()
        return next_tier

    # ── 4. Budget enforcement ────────────────────────────────────────────────

    def set_budget(self, budget_usd: float):
        """Update the budget cap at runtime."""
        self.budget_usd = budget_usd
        self.cap_reached = False
        self.paused_agents = []
        self._persist_state()
        logger.info(f"💰 [CostOptimizer] Budget updated to ${budget_usd:.2f}")

    def should_allow_call(self, agent_id: str, is_critical: bool = False) -> Tuple[bool, str]:
        """
        Check whether a model call should be allowed given the current budget.
        Critical tasks (Healer, Director) are never blocked.
        Returns (allowed, reason).
        """
        if self.cap_reached and not is_critical:
            return False, f"Budget cap ${self.budget_usd:.2f} reached. Non-critical tasks halted."

        pct = self.total_cost / self.budget_usd if self.budget_usd > 0 else 0

        if pct >= 1.0 and not is_critical:
            self.cap_reached = True
            if agent_id not in self.paused_agents:
                self.paused_agents.append(agent_id)
            self._persist_state()
            return False, f"Budget exhausted (${self.total_cost:.3f} / ${self.budget_usd:.2f})"

        return True, "ok"

    def _check_budget_thresholds(self):
        """Fire alerts when spend crosses warning/critical thresholds."""
        if self.budget_usd <= 0:
            return

        pct = self.total_cost / self.budget_usd

        # Avoid duplicate alerts of the same type
        existing_types = {a.alert_type for a in self.alerts}

        if pct >= 1.0 and "cap_reached" not in existing_types:
            self._fire_alert("cap_reached",
                f"Budget cap reached: ${self.total_cost:.3f} of ${self.budget_usd:.2f} spent.",
                pct)
            self.cap_reached = True

        elif pct >= self.critical_threshold and "critical" not in existing_types:
            self._fire_alert("critical",
                f"Critical: {pct*100:.0f}% of budget used "
                f"(${self.total_cost:.3f} / ${self.budget_usd:.2f}).",
                pct)

        elif pct >= self.warning_threshold and "warning" not in existing_types:
            self._fire_alert("warning",
                f"Warning: {pct*100:.0f}% of budget used "
                f"(${self.total_cost:.3f} / ${self.budget_usd:.2f}).",
                pct)

    def _fire_alert(self, alert_type: str, message: str, pct: float):
        alert = CostAlert(
            alert_type=alert_type,
            message=message,
            spend_usd=self.total_cost,
            budget_usd=self.budget_usd,
            pct_used=pct,
            timestamp=datetime.now(timezone.utc).isoformat(),
            project_id=self.project_id,
        )
        self.alerts.append(alert)
        icon = "🔴" if alert_type == "cap_reached" else "🟠" if alert_type == "critical" else "🟡"
        logger.warning(f"{icon} [CostOptimizer] ALERT [{alert_type.upper()}]: {message}")
        self._persist_state()

    # ── 5. Heuristic learning ────────────────────────────────────────────────

    def record_escalation(
        self,
        agent_role: str,
        from_tier: ModelTier,
        to_tier: ModelTier,
        attempt: int,
        task_description: str = "",
        reason: Optional[str] = None,
    ) -> EscalationRecord:
        task_class = self._stem_task(task_description or f"{agent_role} attempt {attempt}")

        for existing in reversed(self.escalation_records):
            if (
                existing.agent_role == agent_role
                and existing.original_tier == from_tier
                and existing.escalated_to == to_tier
                and existing.task_class == task_class
            ):
                self._persist_state()
                return existing

        esc = EscalationRecord(
            task_class=task_class,
            original_tier=from_tier,
            escalated_to=to_tier,
            reason=reason or f"Escalated after failed attempt {attempt}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent_role=agent_role,
        )
        self.escalation_records.append(esc)
        self._update_escalation_heuristic(esc)
        self._persist_state()
        return esc

    def _stem_task(self, task_description: str) -> str:
        """Normalise a task description to a short stem for bucketing."""
        # Take first 6 significant words, lowercased
        words = re.findall(r'\b\w{3,}\b', task_description.lower())
        return " ".join(words[:6])

    def _update_escalation_heuristic(self, record: EscalationRecord):
        """
        If a task class has escalated 3+ times, promote its default tier
        to avoid wasting attempts on underpowered models.
        """
        key = record.task_class
        self._escalation_counts[key] = self._escalation_counts.get(key, 0) + 1

        count = self._escalation_counts[key]
        if count >= 3 and key not in self._learned_tier_overrides:
            self._learned_tier_overrides[key] = record.escalated_to
            logger.info(
                f"🧠 [CostOptimizer] Learned: '{key}' consistently escalates → "
                f"promoting default to {record.escalated_to.value}"
            )

    # ── 6. Reporting / API surface ───────────────────────────────────────────

    def get_summary(self) -> dict:
        """Full cost summary — served by GET /api/cost/summary."""
        pct_used = (self.total_cost / self.budget_usd * 100) if self.budget_usd > 0 else 0

        # Spend breakdown by model tier
        tier_breakdown: Dict[str, dict] = {}
        for rec in self.usage_records:
            t = rec.model_tier.value
            if t not in tier_breakdown:
                tier_breakdown[t] = {"tokens": 0, "cost_usd": 0.0, "calls": 0}
            tier_breakdown[t]["tokens"]   += rec.total_tokens
            tier_breakdown[t]["cost_usd"] += rec.cost_usd
            tier_breakdown[t]["calls"]    += 1

        return {
            "project_id":       self.project_id,
            "total_tokens":     self.total_tokens,
            "total_cost_usd":   round(self.total_cost, 6),
            "budget_usd":       self.budget_usd,
            "pct_budget_used":  round(pct_used, 2),
            "cap_reached":      self.cap_reached,
            "total_calls":      len(self.usage_records),
            "total_escalations":len(self.escalation_records),
            "agent_breakdown":  list(self.agent_spend.values()),
            "tier_breakdown":   tier_breakdown,
            "alerts":           [self._alert_to_dict(a) for a in self.alerts],
            "learned_overrides":{k: v.value for k, v in self._learned_tier_overrides.items()},
            "paused_agents":    self.paused_agents,
            "timestamp":        datetime.now(timezone.utc).isoformat(),
        }

    def get_live_ticker(self) -> dict:
        """Lightweight payload for the frontend CostTicker — polled every 3s."""
        pct = (self.total_cost / self.budget_usd * 100) if self.budget_usd > 0 else 0
        latest_alert = self.alerts[-1] if self.alerts else None
        return {
            "total_tokens":   self.total_tokens,
            "total_cost_usd": round(self.total_cost, 6),
            "budget_usd":     self.budget_usd,
            "pct_budget_used":round(pct, 2),
            "cap_reached":    self.cap_reached,
            "latest_alert":   self._alert_to_dict(latest_alert) if latest_alert else None,
        }

    def get_recent_usage(self, limit: int = 20) -> list:
        """Last N usage records for the live log view."""
        return [self._record_to_dict(r) for r in self.usage_records[-limit:]]

    def get_escalations(self) -> list:
        return [self._esc_to_dict(e) for e in self.escalation_records]

    # ── Private serialisers ──────────────────────────────────────────────────

    def _record_to_dict(self, r: TokenUsageRecord) -> dict:
        return {
            "agent_id":          r.agent_id,
            "agent_role":        r.agent_role,
            "task_description":  r.task_description[:80],
            "model_tier":        r.model_tier.value,
            "model_deployment":  r.model_deployment,
            "prompt_tokens":     r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens":      r.total_tokens,
            "cost_usd":          round(r.cost_usd, 6),
            "timestamp":         r.timestamp,
            "attempt_number":    r.attempt_number,
            "escalated_from":    r.escalated_from.value if r.escalated_from else None,
        }

    def _esc_to_dict(self, e: EscalationRecord) -> dict:
        return {
            "task_class":    e.task_class,
            "original_tier": e.original_tier.value,
            "escalated_to":  e.escalated_to.value,
            "reason":        e.reason,
            "timestamp":     e.timestamp,
            "agent_role":    e.agent_role,
        }

    def _alert_to_dict(self, a: CostAlert) -> dict:
        return {
            "alert_type": a.alert_type,
            "message":    a.message,
            "spend_usd":  round(a.spend_usd, 4),
            "budget_usd": a.budget_usd,
            "pct_used":   round(a.pct_used * 100, 1),
            "timestamp":  a.timestamp,
        }


# ─── Module-level registry: one optimizer per project ───────────────────────
# Keyed by project_id. app.py and main.py both import from here.

    def _state_doc_id(self) -> str:
        return f"cost_optimizer_state_{self.project_id}"

    def _init_state_container(self):
        if not self._state_enabled:
            return None
        try:
            client = CosmosClient.from_connection_string(COSMOS_CONNECTION_STR)
            db = client.get_database_client(DATABASE_NAME)
            return db.get_container_client(COST_STATE_CONTAINER)
        except Exception as e:
            logger.warning(f"⚠️  [CostOptimizer] Cosmos state unavailable: {e}")
            self._state_enabled = False
            return None

    def _persist_state(self):
        if not self._state_enabled or self.state_container is None:
            return
        try:
            self.state_container.upsert_item({
                "id": self._state_doc_id(),
                "project_id": self.project_id,
                "type": "cost_optimizer_state",
                "budget_usd": self.budget_usd,
                "warning_threshold": self.warning_threshold,
                "critical_threshold": self.critical_threshold,
                "total_tokens": self.total_tokens,
                "total_cost": self.total_cost,
                "cap_reached": self.cap_reached,
                "paused_agents": list(self.paused_agents),
                "agent_spend": list(self.agent_spend.values()),
                "usage_records": [self._record_to_dict(r) for r in self.usage_records],
                "escalation_records": [self._esc_to_dict(e) for e in self.escalation_records],
                "alerts": [self._alert_to_dict(a) for a in self.alerts],
                "learned_overrides": {k: v.value for k, v in self._learned_tier_overrides.items()},
                "escalation_counts": dict(self._escalation_counts),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.warning(f"⚠️  [CostOptimizer] Could not persist state: {e}")
            self._state_enabled = False
            self.state_container = None

    def _load_persisted_state(self):
        if not self._state_enabled or self.state_container is None:
            return
        try:
            doc = self.state_container.read_item(item=self._state_doc_id(), partition_key=self.project_id)
        except CosmosExceptions.CosmosResourceNotFoundError:
            return
        except Exception as e:
            logger.warning(f"⚠️  [CostOptimizer] Could not load persisted state: {e}")
            self._state_enabled = False
            self.state_container = None
            return

        self.budget_usd = float(doc.get("budget_usd", self.budget_usd))
        self.warning_threshold = float(doc.get("warning_threshold", self.warning_threshold))
        self.critical_threshold = float(doc.get("critical_threshold", self.critical_threshold))
        self.total_tokens = int(doc.get("total_tokens", 0))
        self.total_cost = float(doc.get("total_cost", 0.0))
        self.cap_reached = bool(doc.get("cap_reached", False))
        self.paused_agents = list(doc.get("paused_agents", []))
        self.agent_spend = {
            item["agent_id"]: item
            for item in doc.get("agent_spend", [])
            if item.get("agent_id")
        }
        self.usage_records = [self._record_from_dict(item) for item in doc.get("usage_records", [])]
        self.escalation_records = [self._esc_from_dict(item) for item in doc.get("escalation_records", [])]
        self.alerts = [self._alert_from_dict(item) for item in doc.get("alerts", [])]
        self._learned_tier_overrides = {
            key: ModelTier(value)
            for key, value in doc.get("learned_overrides", {}).items()
        }
        self._escalation_counts = {
            key: int(value)
            for key, value in doc.get("escalation_counts", {}).items()
        }

    def _record_from_dict(self, record: dict) -> TokenUsageRecord:
        return TokenUsageRecord(
            agent_id=record["agent_id"],
            agent_role=record["agent_role"],
            task_description=record["task_description"],
            model_tier=ModelTier(record["model_tier"]),
            model_deployment=record["model_deployment"],
            prompt_tokens=int(record["prompt_tokens"]),
            completion_tokens=int(record["completion_tokens"]),
            total_tokens=int(record["total_tokens"]),
            cost_usd=float(record["cost_usd"]),
            timestamp=record["timestamp"],
            attempt_number=int(record.get("attempt_number", 1)),
            escalated_from=ModelTier(record["escalated_from"]) if record.get("escalated_from") else None,
            project_id=self.project_id,
        )

    def _esc_from_dict(self, esc: dict) -> EscalationRecord:
        return EscalationRecord(
            task_class=esc["task_class"],
            original_tier=ModelTier(esc["original_tier"]),
            escalated_to=ModelTier(esc["escalated_to"]),
            reason=esc["reason"],
            timestamp=esc["timestamp"],
            agent_role=esc["agent_role"],
        )

    def _alert_from_dict(self, alert: dict) -> CostAlert:
        pct_used = float(alert.get("pct_used", 0.0))
        return CostAlert(
            alert_type=alert["alert_type"],
            message=alert["message"],
            spend_usd=float(alert["spend_usd"]),
            budget_usd=float(alert["budget_usd"]),
            pct_used=(pct_used / 100.0) if pct_used > 1 else pct_used,
            timestamp=alert["timestamp"],
            project_id=self.project_id,
        )

    def delete_persisted_state(self):
        if not self._state_enabled or self.state_container is None:
            return
        try:
            self.state_container.delete_item(item=self._state_doc_id(), partition_key=self.project_id)
        except CosmosExceptions.CosmosResourceNotFoundError:
            return
        except Exception as e:
            logger.warning(f"⚠️  [CostOptimizer] Could not delete persisted state: {e}")
            self._state_enabled = False
            self.state_container = None


_optimizers: Dict[str, CostOptimizer] = {}


def get_optimizer(project_id: str, budget_usd: float = 5.0) -> CostOptimizer:
    """Get or create the CostOptimizer for a project."""
    if project_id not in _optimizers:
        _optimizers[project_id] = CostOptimizer(project_id, budget_usd)
    return _optimizers[project_id]


def list_optimizers() -> Dict[str, CostOptimizer]:
    return _optimizers
