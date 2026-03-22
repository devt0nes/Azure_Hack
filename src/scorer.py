"""
scorer.py
Core Reputation Scoring Engine — v3 metric set.

Weights (sum to 1.0):
  contract_fidelity          0.25  schema correctness; broken schema breaks all downstream
  downstream_satisfaction    0.25  strongest peer signal; agents cannot fake this
  pre_healer_test_pass_rate  0.20  objective QA signal, fully Healer-independent
  security_compliance_score  0.20  OWASP/IAM/secrets from Security Reviewer
  token_efficiency           0.10  cost signal; important but secondary to correctness
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Tuple

from .schemas import AgentReputationDocument, DimensionalScores, RawEngagementMetrics


# ──────────────────────────────────────────────
# Metric weights
# ──────────────────────────────────────────────

METRIC_WEIGHTS: dict[str, float] = {
    "contract_fidelity":         0.25,
    "downstream_satisfaction":   0.25,
    "pre_healer_test_pass_rate": 0.20,
    "security_compliance_score": 0.20,
    "token_efficiency":          0.10,
}
assert abs(sum(METRIC_WEIGHTS.values()) - 1.0) < 1e-9


# ──────────────────────────────────────────────
# Adaptive EMA alpha
# ──────────────────────────────────────────────

ALPHA_CEIL:  float = 0.60
ALPHA_FLOOR: float = 0.05
DECAY_RATE:  float = 10.0


def compute_alpha(weighted_engagement_count: float) -> float:
    return ALPHA_FLOOR + (ALPHA_CEIL - ALPHA_FLOOR) * math.exp(
        -weighted_engagement_count / DECAY_RATE
    )


# ──────────────────────────────────────────────
# Engagement scoring
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class EngagementScore:
    composite:         float
    dimensional:       DimensionalScores
    complexity_weight: float
    raw_metrics:       RawEngagementMetrics


def score_engagement(metrics: RawEngagementMetrics) -> EngagementScore:
    raw = {
        "contract_fidelity":         metrics.contract_fidelity,
        "downstream_satisfaction":   metrics.downstream_satisfaction,
        "pre_healer_test_pass_rate": metrics.pre_healer_test_pass_rate,
        "security_compliance_score": metrics.security_compliance_score,
        "token_efficiency":          metrics.token_efficiency,
    }
    composite = sum(METRIC_WEIGHTS[k] * v for k, v in raw.items())
    return EngagementScore(
        composite=         composite,
        dimensional=       DimensionalScores(**raw),
        complexity_weight= metrics.complexity.complexity_weight,
        raw_metrics=       metrics,
    )


# ──────────────────────────────────────────────
# Reputation document update
# ──────────────────────────────────────────────

def update_reputation(
    doc:        AgentReputationDocument,
    engagement: EngagementScore,
) -> Tuple[AgentReputationDocument, float, float]:
    """
    Apply a new engagement via complexity-weighted EMA.
    Returns: (updated_doc, old_score, new_score)
    """
    old_score       = doc.reputation_score
    base_alpha      = compute_alpha(doc.weighted_engagement_count)
    effective_alpha = base_alpha * engagement.complexity_weight

    new_score = _ema(old_score, engagement.composite, effective_alpha)

    old_dim = doc.dimensional_scores
    new_dim = DimensionalScores(
        contract_fidelity=         _ema(old_dim.contract_fidelity,         engagement.dimensional.contract_fidelity,         effective_alpha),
        downstream_satisfaction=   _ema(old_dim.downstream_satisfaction,   engagement.dimensional.downstream_satisfaction,   effective_alpha),
        pre_healer_test_pass_rate= _ema(old_dim.pre_healer_test_pass_rate, engagement.dimensional.pre_healer_test_pass_rate, effective_alpha),
        security_compliance_score= _ema(old_dim.security_compliance_score, engagement.dimensional.security_compliance_score, effective_alpha),
        token_efficiency=          _ema(old_dim.token_efficiency,          engagement.dimensional.token_efficiency,          effective_alpha),
    )

    updated = doc.model_copy(update={
        "reputation_score":          new_score,
        "dimensional_scores":        new_dim,
        "total_engagements":         doc.total_engagements + 1,
        "weighted_engagement_count": doc.weighted_engagement_count + engagement.complexity_weight,
        "last_updated_at":           datetime.now(timezone.utc),
    })
    return updated, old_score, new_score


def _ema(old: float, new: float, alpha: float) -> float:
    return max(0.0, min(alpha * new + (1 - alpha) * old, 1.0))


# ──────────────────────────────────────────────
# Normalisation helpers  (called by Director / orchestrator)
# ──────────────────────────────────────────────

ROLE_TOKEN_BASELINES: dict[str, float] = {
    "backend_engineer":     1 / 50,
    "frontend_engineer":    1 / 60,
    "database_architect":   1 / 80,
    "qa_engineer":          1 / 70,
    "documentation_writer": 1 / 5,
    "security_reviewer":    1 / 120,
    "devops_engineer":      1 / 90,
    "cost_optimizer":       1 / 100,
    "healer_agent":         1 / 110,
    "default":              1 / 75,
}

def normalise_token_efficiency(
    output_units:    float,
    tokens_consumed: int,
    agent_role:      str,
) -> float:
    if tokens_consumed == 0:
        return 0.0
    baseline = ROLE_TOKEN_BASELINES.get(agent_role, ROLE_TOKEN_BASELINES["default"])
    x = 3.0 * (output_units / tokens_consumed / baseline - 1.0)
    return 1.0 / (1.0 + math.exp(-x))


def normalise_test_pass_rate(passing_tests: int, total_tests: int) -> float:
    if total_tests <= 0:
        return 1.0
    return max(0.0, min(passing_tests / total_tests, 1.0))


SECURITY_FINDING_PENALTIES: dict[str, float] = {
    "critical": 0.25,
    "high":     0.10,
    "medium":   0.04,
    "low":      0.01,
}

SECURITY_CATEGORY_WEIGHTS: dict[str, float] = {
    "owasp":   0.40,
    "iam":     0.30,
    "secrets": 0.20,
    "deps":    0.10,
}

def normalise_security_score(findings: dict[str, dict[str, int]]) -> float:
    category_scores: dict[str, float] = {}
    for category, counts in findings.items():
        penalty = sum(SECURITY_FINDING_PENALTIES.get(sev, 0.0) * n for sev, n in counts.items())
        category_scores[category] = max(0.0, 1.0 - penalty)

    if not category_scores:
        return 1.0

    total_weight = sum(SECURITY_CATEGORY_WEIGHTS.get(c, 0.0) for c in category_scores)
    if total_weight == 0:
        return sum(category_scores.values()) / len(category_scores)

    return sum(SECURITY_CATEGORY_WEIGHTS.get(c, 0.0) * s for c, s in category_scores.items()) / total_weight


def normalise_downstream_satisfaction(a2a_correction_requests: int) -> float:
    return max(0.0, 1.0 - (a2a_correction_requests * 0.20))