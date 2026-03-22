"""
schemas.py
Cosmos DB document schemas for the Reputation Scoring System.
Container : agent_catalog  |  Partition key : /agent_id

Metric set (v3):
  contract_fidelity          25%  schema correctness against AEG output contract
  downstream_satisfaction    25%  peer signal: A2A correction requests from dependents
  pre_healer_test_pass_rate  20%  QA Agent test results on raw output, before Healer runs
  security_compliance_score  20%  Security Reviewer OWASP/IAM/secrets/deps structured output
  token_efficiency           10%  output units per token, sigmoid-scaled against role baseline

Why pre_healer_test_pass_rate replaces healer_intervention_depth:
  healer_intervention_depth was Healer-dependent — if the Healer missed issues the
  agent scored well unfairly; if the Healer over-patched the agent was penalised
  unfairly. pre_healer_test_pass_rate is fully independent: QA runs the test suite
  against raw agent output before the Healer is invoked. Pass/fail is objective,
  already available in the pipeline, and not influenced by any other agent's quality.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AgentStatus(str, Enum):
    ACTIVE       = "active"
    SCORE_REVIEW = "score_review"
    SUSPENDED    = "suspended"
    RETIRED      = "retired"


class ModelTier(str, Enum):
    PHI4       = "phi4"
    GPT4O_MINI = "gpt4o_mini"
    GPT4O      = "gpt4o"
    GPT4O_O1   = "gpt4o_o1"


class BuildComplexity(BaseModel):
    """
    Complexity multiplier in [0.1, 1.0] used to weight EMA updates.
    Prevents agents farming trivial builds to inflate scores (§6.8.2).
    """
    aeg_node_count:         int       = Field(..., ge=1)
    aeg_edge_count:         int       = Field(..., ge=0)
    total_tokens_consumed:  int       = Field(..., ge=0)
    downstream_agent_count: int       = Field(..., ge=0)
    model_tier:             ModelTier

    @property
    def complexity_weight(self) -> float:
        TIER = {
            ModelTier.PHI4:       0.20,
            ModelTier.GPT4O_MINI: 0.50,
            ModelTier.GPT4O:      0.80,
            ModelTier.GPT4O_O1:   1.00,
        }
        aeg    = min((self.aeg_node_count / 20 + self.aeg_edge_count / 40) / 2, 1.0)
        tokens = min(self.total_tokens_consumed / 200_000, 1.0)
        tier   = TIER[self.model_tier]
        ds     = min(self.downstream_agent_count / 8, 1.0)
        return max(0.1, min((aeg + tokens + tier + ds) / 4, 1.0))


class RawEngagementMetrics(BaseModel):
    """
    Normalised [0, 1] performance observations for one agent engagement.
    Collected by the Director at the end of each agent's participation in a build.
    Stored as document_type='engagement_record' for velocity queries.
    """
    engagement_id:     str      = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id:          str
    build_id:          str
    owner_azure_ad_id: str
    recorded_at:       datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    complexity:        BuildComplexity

    contract_fidelity: float = Field(..., ge=0.0, le=1.0,
        description=(
            "Fraction of AEG output contract schema fields satisfied exactly. "
            "Computed by the Validator Agent diffing actual vs expected output spec."
        ))

    downstream_satisfaction: float = Field(..., ge=0.0, le=1.0,
        description=(
            "Peer signal from dependent agents. Starts at 1.0. "
            "Each A2A correction request deducts 0.2, floor 0. "
            "Logged in the AEG message bus — not self-reported."
        ))

    pre_healer_test_pass_rate: float = Field(..., ge=0.0, le=1.0,
        description=(
            "Fraction of QA Agent tests that pass on raw agent output, "
            "measured BEFORE the Healer is invoked. "
            "Formula: passing_tests / total_tests. "
            "Fully Healer-independent."
        ))

    security_compliance_score: float = Field(..., ge=0.0, le=1.0,
        description=(
            "Structured output from the Security Reviewer Agent. "
            "Weighted composite: OWASP 40%, IAM 30%, secrets 20%, deps 10%. "
            "Critical: -0.25, high: -0.10, medium: -0.04, low: -0.01, floor 0."
        ))

    token_efficiency: float = Field(..., ge=0.0, le=1.0,
        description=(
            "Meaningful output units per token, sigmoid-scaled against role baseline. "
            "Use normalise_token_efficiency() before setting this field."
        ))

    @field_validator("downstream_satisfaction", "pre_healer_test_pass_rate",
                     "security_compliance_score", mode="before")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(float(v), 1.0))


class DimensionalScores(BaseModel):
    """Per-dimension EMA scores. All start at 0.5 (neutral seed)."""
    contract_fidelity:         float = Field(0.5, ge=0.0, le=1.0)
    downstream_satisfaction:   float = Field(0.5, ge=0.0, le=1.0)
    pre_healer_test_pass_rate: float = Field(0.5, ge=0.0, le=1.0)
    security_compliance_score: float = Field(0.5, ge=0.0, le=1.0)
    token_efficiency:          float = Field(0.5, ge=0.0, le=1.0)


class AntiGamingFlags(BaseModel):
    score_under_review:       bool               = False
    review_reason:            Optional[str]      = None
    review_triggered_at:      Optional[datetime] = None
    community_report_count:   int                = Field(0, ge=0)
    last_report_window_start: Optional[datetime] = None


class AgentReputationDocument(BaseModel):
    """
    Top-level Cosmos DB document. Partition key: agent_id.
    Neutral seed = 0.5 for brand-new agents (§4.3.3).
    """
    id:                        str         = Field(default_factory=lambda: str(uuid.uuid4()))
    document_type:             str         = "agent_reputation"
    agent_id:                  str
    agent_name:                str
    publisher_azure_ad:        str
    status:                    AgentStatus = AgentStatus.ACTIVE
    reputation_score:          float       = Field(0.5, ge=0.0, le=1.0)
    dimensional_scores:        DimensionalScores = Field(default_factory=DimensionalScores)
    total_engagements:         int         = 0
    weighted_engagement_count: float       = 0.0
    anti_gaming:               AntiGamingFlags   = Field(default_factory=AntiGamingFlags)
    created_at:                datetime    = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated_at:           datetime    = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_cosmos_dict(self) -> dict:
        return self.model_dump(mode="json")