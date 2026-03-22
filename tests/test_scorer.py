"""
test_scorer.py — v3 metric set.
Run from repo root: pytest tests/ -v
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.schemas import BuildComplexity, ModelTier, RawEngagementMetrics, AgentReputationDocument
from src.scorer import (
    METRIC_WEIGHTS, compute_alpha, score_engagement, update_reputation,
    normalise_token_efficiency, normalise_test_pass_rate,
    normalise_security_score, normalise_downstream_satisfaction,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_complexity(nodes=5, edges=4, tokens=50_000, downstream=2, tier=ModelTier.GPT4O):
    return BuildComplexity(aeg_node_count=nodes, aeg_edge_count=edges,
                           total_tokens_consumed=tokens, downstream_agent_count=downstream,
                           model_tier=tier)

def make_metrics(**overrides):
    defaults = dict(
        agent_id="a1", build_id="b1", owner_azure_ad_id="user-aad",
        contract_fidelity=0.9,
        downstream_satisfaction=1.0,
        pre_healer_test_pass_rate=0.88,
        security_compliance_score=0.85,
        token_efficiency=0.75,
        complexity=make_complexity(),
    )
    defaults.update(overrides)
    return RawEngagementMetrics(**defaults)

def make_doc(score=0.5, weighted_n=0.0):
    return AgentReputationDocument(agent_id="a1", agent_name="T", publisher_azure_ad="pub",
                                   reputation_score=score, weighted_engagement_count=weighted_n)


# ── Weights ───────────────────────────────────────────────────────────────────

def test_weights_sum_to_one():
    assert abs(sum(METRIC_WEIGHTS.values()) - 1.0) < 1e-9

def test_no_healer_metric():
    assert "healer_intervention_depth" not in METRIC_WEIGHTS
    assert "task_success_rate" not in METRIC_WEIGHTS
    assert "time_to_completion" not in METRIC_WEIGHTS

def test_pre_healer_test_rate_present():
    assert "pre_healer_test_pass_rate" in METRIC_WEIGHTS
    assert METRIC_WEIGHTS["pre_healer_test_pass_rate"] == 0.20

def test_security_weight():
    assert METRIC_WEIGHTS["security_compliance_score"] == 0.20


# ── score_engagement ──────────────────────────────────────────────────────────

def test_perfect_score_is_one():
    m = make_metrics(contract_fidelity=1.0, downstream_satisfaction=1.0,
                     pre_healer_test_pass_rate=1.0, security_compliance_score=1.0,
                     token_efficiency=1.0)
    assert abs(score_engagement(m).composite - 1.0) < 1e-9

def test_zero_score_is_zero():
    m = make_metrics(contract_fidelity=0.0, downstream_satisfaction=0.0,
                     pre_healer_test_pass_rate=0.0, security_compliance_score=0.0,
                     token_efficiency=0.0)
    assert abs(score_engagement(m).composite - 0.0) < 1e-9

def test_pre_healer_weight():
    m = make_metrics(contract_fidelity=0.0, downstream_satisfaction=0.0,
                     pre_healer_test_pass_rate=1.0, security_compliance_score=0.0,
                     token_efficiency=0.0)
    assert abs(score_engagement(m).composite - 0.20) < 1e-9

def test_security_weight_isolated():
    m = make_metrics(contract_fidelity=0.0, downstream_satisfaction=0.0,
                     pre_healer_test_pass_rate=0.0, security_compliance_score=1.0,
                     token_efficiency=0.0)
    assert abs(score_engagement(m).composite - 0.20) < 1e-9


# ── update_reputation ─────────────────────────────────────────────────────────

def test_good_engagement_raises_score():
    doc = make_doc(score=0.5)
    m   = make_metrics(contract_fidelity=1.0, downstream_satisfaction=1.0,
                       pre_healer_test_pass_rate=1.0, security_compliance_score=1.0,
                       token_efficiency=1.0)
    _, old, new = update_reputation(doc, score_engagement(m))
    assert new > old

def test_failing_tests_lowers_score():
    doc = make_doc(score=0.9)
    m   = make_metrics(contract_fidelity=1.0, downstream_satisfaction=1.0,
                       pre_healer_test_pass_rate=0.0, security_compliance_score=1.0,
                       token_efficiency=1.0)
    _, old, new = update_reputation(doc, score_engagement(m))
    assert new < old

def test_security_failure_lowers_score():
    doc = make_doc(score=0.9)
    m   = make_metrics(contract_fidelity=1.0, downstream_satisfaction=1.0,
                       pre_healer_test_pass_rate=1.0, security_compliance_score=0.0,
                       token_efficiency=1.0)
    _, old, new = update_reputation(doc, score_engagement(m))
    assert new < old

def test_low_complexity_moves_score_less():
    doc  = make_doc(score=0.5, weighted_n=30.0)
    perf = dict(contract_fidelity=1.0, downstream_satisfaction=1.0,
                pre_healer_test_pass_rate=1.0, security_compliance_score=1.0,
                token_efficiency=1.0)
    phi4 = make_complexity(nodes=2, edges=1, tokens=3_000, downstream=0, tier=ModelTier.PHI4)
    o1   = make_complexity(nodes=14, edges=20, tokens=180_000, downstream=7, tier=ModelTier.GPT4O_O1)
    _, _, new_phi4 = update_reputation(doc, score_engagement(make_metrics(complexity=phi4, **perf)))
    _, _, new_o1   = update_reputation(doc, score_engagement(make_metrics(complexity=o1, **perf)))
    assert new_o1 > new_phi4

def test_engagement_count_increments():
    doc = make_doc()
    updated, _, _ = update_reputation(doc, score_engagement(make_metrics()))
    assert updated.total_engagements == 1

def test_score_stays_in_range():
    doc = make_doc(score=0.99)
    m   = make_metrics(contract_fidelity=1.0, downstream_satisfaction=1.0,
                       pre_healer_test_pass_rate=1.0, security_compliance_score=1.0,
                       token_efficiency=1.0)
    updated, _, new = update_reputation(doc, score_engagement(m))
    assert 0.0 <= new <= 1.0


# ── normalise_test_pass_rate ──────────────────────────────────────────────────

def test_all_pass_is_one():
    assert normalise_test_pass_rate(100, 100) == 1.0

def test_all_fail_is_zero():
    assert normalise_test_pass_rate(0, 100) == 0.0

def test_partial_pass_correct():
    assert abs(normalise_test_pass_rate(75, 100) - 0.75) < 1e-9

def test_no_tests_returns_one():
    assert normalise_test_pass_rate(0, 0) == 1.0

def test_independent_of_healer():
    r1 = normalise_test_pass_rate(80, 100)
    r2 = normalise_test_pass_rate(80, 100)
    assert r1 == r2


# ── normalise_security_score ──────────────────────────────────────────────────

def test_zero_findings_is_one():
    findings = {
        "owasp":   {"critical": 0, "high": 0, "medium": 0, "low": 0},
        "iam":     {"critical": 0, "high": 0, "medium": 0, "low": 0},
        "secrets": {"critical": 0},
        "deps":    {"critical": 0},
    }
    assert normalise_security_score(findings) == 1.0

def test_high_finding_reduces_score():
    findings = {"owasp": {"critical": 0, "high": 1, "medium": 0, "low": 0}}
    assert normalise_security_score(findings) < 1.0

def test_critical_finding_heavy_penalty():
    findings = {"owasp": {"critical": 4}}
    assert normalise_security_score(findings) == 0.0


# ── normalise_downstream_satisfaction ────────────────────────────────────────

def test_no_corrections_is_one():
    assert normalise_downstream_satisfaction(0) == 1.0

def test_five_corrections_floors():
    assert normalise_downstream_satisfaction(5) == 0.0

def test_one_correction_is_80pct():
    assert abs(normalise_downstream_satisfaction(1) - 0.8) < 1e-9


# ── normalise_token_efficiency ────────────────────────────────────────────────

def test_at_baseline_is_half():
    baseline = 1 / 50
    score    = normalise_token_efficiency(1.0, int(1.0 / baseline), "backend_engineer")
    assert abs(score - 0.5) < 0.02


# ── BuildComplexity ───────────────────────────────────────────────────────────

def test_trivial_weight_low():
    assert make_complexity(nodes=2, edges=1, tokens=3_000, downstream=0, tier=ModelTier.PHI4).complexity_weight < 0.3

def test_complex_weight_high():
    assert make_complexity(nodes=18, edges=35, tokens=195_000, downstream=7, tier=ModelTier.GPT4O_O1).complexity_weight > 0.8

def test_weight_in_range():
    for tier in ModelTier:
        assert 0.1 <= make_complexity(tier=tier).complexity_weight <= 1.0