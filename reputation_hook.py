"""
reputation_hook.py
------------------
Drop-in engagement recorder for the main.py orchestrator.

ADD THIS FILE to the agent-library root, then add two calls in main.py:

  1) Near the top of main.py (with other imports):
       from reputation_hook import build_engagement_metrics, post_reputation_engagement

  2) After each agent completes (find the block where agent.status = COMPLETED
     and agent output is saved), add:
       await post_reputation_engagement(
           agent_id=agent.agent_id,     # or agent.role / however it's keyed
           agent_role=agent.role,
           project_id=project_id,
           owner_id=owner_id,
           tokens_consumed=agent.tokens_used,        # int
           output_char_count=len(agent.output or ""),# proxy for output_units
           aeg_node_count=len(agents),               # total agents in this run
           aeg_edge_count=len(agents) - 1,           # approx dependency edges
           downstream_agent_count=...,               # dependents of this agent
           model_tier_str=agent.model_tier,          # "simple"|"complex" etc.
           contract_fidelity=...,                    # 0‒1, from Validator output
           a2a_correction_requests=...,              # int, from ledger
           qa_passing=...,                           # int, from QA output
           qa_total=...,                             # int, from QA output
           security_findings=...,                    # dict, from Security agent
       )

All parameters have safe defaults so partial data still produces a valid score.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def build_engagement_metrics(
    agent_id:               str,
    agent_role:             str,
    project_id:             str,
    owner_id:               str,
    tokens_consumed:        int   = 50_000,
    output_char_count:      float = 1_000.0,
    aeg_node_count:         int   = 5,
    aeg_edge_count:         int   = 4,
    downstream_agent_count: int   = 2,
    model_tier_str:         str   = "complex",   # "simple" | "intermediate" | "complex" | "high-reasoning"
    contract_fidelity:      float = 0.75,
    a2a_correction_requests: int  = 0,
    qa_passing:             int   = 8,
    qa_total:               int   = 10,
    security_findings:      Optional[dict] = None,
):
    """
    Assembles a RawEngagementMetrics object from orchestrator data.
    All normalisation helpers are applied here so callers pass raw counts.
    Returns None if the src package is unavailable (graceful degradation).
    """
    try:
        from src.schemas import BuildComplexity, ModelTier, RawEngagementMetrics
        from src.scorer import (
            normalise_token_efficiency,
            normalise_test_pass_rate,
            normalise_downstream_satisfaction,
            normalise_security_score,
        )

        # Map orchestrator model_tier strings → scorer ModelTier
        tier_map = {
            "simple":         ModelTier.PHI4,
            "phi4":           ModelTier.PHI4,
            "intermediate":   ModelTier.GPT4O_MINI,
            "gpt4o_mini":     ModelTier.GPT4O_MINI,
            "complex":        ModelTier.GPT4O,
            "gpt4o":          ModelTier.GPT4O,
            "high-reasoning": ModelTier.GPT4O_O1,
            "gpt4o_o1":       ModelTier.GPT4O_O1,
        }
        tier = tier_map.get(model_tier_str.lower(), ModelTier.GPT4O)

        complexity = BuildComplexity(
            aeg_node_count=         aeg_node_count,
            aeg_edge_count=         aeg_edge_count,
            total_tokens_consumed=  tokens_consumed,
            downstream_agent_count= downstream_agent_count,
            model_tier=             tier,
        )

        # Apply normalisers
        token_eff   = normalise_token_efficiency(output_char_count, tokens_consumed, agent_role)
        pass_rate   = normalise_test_pass_rate(qa_passing, qa_total)
        ds_sat      = normalise_downstream_satisfaction(a2a_correction_requests)
        sec_score   = normalise_security_score(security_findings or {
            "owasp":   {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "iam":     {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "secrets": {"critical": 0},
            "deps":    {"critical": 0},
        })

        return RawEngagementMetrics(
            agent_id=                  agent_id,
            build_id=                  project_id,
            owner_azure_ad_id=         owner_id,
            complexity=                complexity,
            contract_fidelity=         max(0.0, min(contract_fidelity, 1.0)),
            downstream_satisfaction=   ds_sat,
            pre_healer_test_pass_rate= pass_rate,
            security_compliance_score= sec_score,
            token_efficiency=          token_eff,
        )

    except ImportError as e:
        logger.warning(f"⚠️  reputation_hook: src package not available — {e}")
        return None
    except Exception as e:
        logger.warning(f"⚠️  reputation_hook: could not build metrics for {agent_id}: {e}")
        return None


async def post_reputation_engagement(
    agent_id:               str,
    agent_role:             str,
    project_id:             str,
    owner_id:               str,
    **kwargs,
) -> Optional[dict]:
    """
    Async wrapper — builds metrics and calls agents_router.record_agent_engagement().
    Returns the result dict (old_score, new_score, flagged, …) or None on failure.
    Safe to call even if reputation service is down.
    """
    metrics = build_engagement_metrics(
        agent_id=   agent_id,
        agent_role= agent_role,
        project_id= project_id,
        owner_id=   owner_id,
        **kwargs,
    )
    if metrics is None:
        return None

    try:
        from agents_router import record_agent_engagement
        return record_agent_engagement(metrics)
    except Exception as e:
        logger.warning(f"⚠️  reputation_hook: engagement post failed for {agent_id}: {e}")
        return None