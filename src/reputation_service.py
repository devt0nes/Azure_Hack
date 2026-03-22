"""
reputation_service.py
Top-level ReputationService — the only class agents_router imports.

Orchestrates per-engagement:
  1. Persist raw engagement record (for velocity queries)
  2. Load reputation doc (fail-fast if missing)
  3. Compute engagement score via v3 metric weights
  4. Apply complexity-weighted EMA update
  5. Run velocity anomaly check
  6. Persist updated document

Also exposes:
  seed_new_agent()            create neutral doc for a new agent (§4.3.3)
  seed_builtin_agent()        seed system/builtin agents (bypasses publisher verification)
  file_community_report()     called from Command Center UI
  resolve_audit()             called by human reviewers
  selection_score()           Director uses this in Stage 3 catalog ranking
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .anti_gaming import (
    AntiGamingConfig, AuditResolver, AzureADVerifier,
    CommunityReportHandler, ReportResult, VelocityDetector, VerificationResult,
)
from .cosmos_store import CosmosReputationStore
from .schemas import AgentReputationDocument, AgentStatus, DimensionalScores, RawEngagementMetrics
from .scorer import EngagementScore, score_engagement, update_reputation

logger = logging.getLogger(__name__)


@dataclass
class EngagementResult:
    doc:         AgentReputationDocument
    old_score:   float
    new_score:   float
    flagged:     bool
    flag_reason: Optional[str]


class ReputationService:

    def __init__(
        self,
        store:    CosmosReputationStore,
        verifier: AzureADVerifier  = None,
        cfg:      AntiGamingConfig = None,
    ):
        self._store    = store
        self._verifier = verifier or AzureADVerifier()
        self._cfg      = cfg      or AntiGamingConfig()
        self._velocity = VelocityDetector(store, self._cfg)
        self._reporter = CommunityReportHandler(self._cfg)

    @classmethod
    def from_env(cls) -> "ReputationService":
        return cls(store=CosmosReputationStore.from_env())

    # ── Core: record one engagement ──────────────

    def record_engagement(self, metrics: RawEngagementMetrics) -> EngagementResult:
        self._store.save_engagement_record(metrics)

        doc = self._store.get_reputation(metrics.agent_id)
        if doc is None:
            raise ValueError(
                f"Agent {metrics.agent_id} has no reputation document. "
                "Call seed_new_agent() or seed_builtin_agent() first."
            )

        engagement: EngagementScore       = score_engagement(metrics)
        updated_doc, old_score, new_score = update_reputation(doc, engagement)

        analysis = self._velocity.analyse(updated_doc, new_score, old_score)
        if analysis.is_anomalous:
            updated_doc = self._velocity.apply_flag(updated_doc, analysis)

        self._store.save_reputation(updated_doc)
        logger.info("engagement agent=%s build=%s %.4f→%.4f flagged=%s",
                    metrics.agent_id, metrics.build_id, old_score, new_score, analysis.is_anomalous)

        return EngagementResult(
            doc=         updated_doc,
            old_score=   old_score,
            new_score=   new_score,
            flagged=     analysis.is_anomalous,
            flag_reason= analysis.reason if analysis.is_anomalous else None,
        )

    # ── Seed new agent (§4.3.3) ──────────────────

    def seed_new_agent(
        self,
        agent_id:           str,
        agent_name:         str,
        publisher_azure_ad: str,
        account_age_days:   int = 0,
        prior_builds:       int = 0,
    ) -> AgentReputationDocument:
        result: VerificationResult = self._verifier.verify(
            publisher_azure_ad, account_age_days, prior_builds
        )
        if not result.is_verified:
            raise PermissionError(f"Publisher not verified: {result.reason}")

        existing = self._store.get_reputation(agent_id)
        if existing:
            return existing

        doc = AgentReputationDocument(
            agent_id=           agent_id,
            agent_name=         agent_name,
            publisher_azure_ad= publisher_azure_ad,
            reputation_score=   0.5,
            dimensional_scores= DimensionalScores(),
        )
        self._store.save_reputation(doc)
        logger.info("seeded agent=%s publisher=%s", agent_id, publisher_azure_ad)
        return doc

    # ── Seed builtin/system agents (bypasses publisher verification) ──

    def seed_builtin_agent(
        self,
        agent_id:         str,
        agent_name:       str,
        initial_score:    float = 0.5,
    ) -> AgentReputationDocument:
        """
        Seeds reputation docs for builtin catalog agents.
        Bypasses AzureADVerifier — these are trusted system agents.
        Idempotent: returns existing doc without modification if already seeded.
        """
        existing = self._store.get_reputation(agent_id)
        if existing:
            return existing

        doc = AgentReputationDocument(
            agent_id=           agent_id,
            agent_name=         agent_name,
            publisher_azure_ad= "system-builtin",
            reputation_score=   max(0.0, min(initial_score, 1.0)),
            dimensional_scores= DimensionalScores(),
        )
        self._store.save_reputation(doc)
        logger.info("seeded builtin agent=%s initial_score=%.2f", agent_id, initial_score)
        return doc

    # ── Community reports ────────────────────────

    def file_community_report(
        self,
        agent_id:             str,
        reporter_azure_ad_id: str,
        notes:                str = "",
    ) -> ReportResult:
        doc = self._store.get_reputation(agent_id)
        if doc is None:
            raise ValueError(f"Unknown agent: {agent_id}")

        since = (
            doc.anti_gaming.last_report_window_start
            or datetime.now(timezone.utc) - timedelta(days=self._cfg.REPORT_WINDOW_DAYS)
        )
        prior_ids   = self._store.get_reporter_ids_in_window(agent_id, since)
        updated_doc, result = self._reporter.file_report(doc, reporter_azure_ad_id, prior_ids)

        if result.accepted:
            self._store.save_community_report(agent_id, reporter_azure_ad_id, notes)
            self._store.save_reputation(updated_doc)

        return result

    # ── Human audit resolution ───────────────────

    def resolve_audit(
        self,
        agent_id: str,
        auditor:  str,
        action:   str,   # "restore" | "retire"
        notes:    str = "",
    ) -> AgentReputationDocument:
        doc = self._store.get_reputation(agent_id)
        if doc is None:
            raise ValueError(f"Unknown agent: {agent_id}")

        if action == "restore":
            updated = AuditResolver.clear_and_restore(doc, auditor, notes)
        elif action == "retire":
            updated = AuditResolver.retire(doc, auditor, notes)
        else:
            raise ValueError(f"action must be 'restore' or 'retire', got {action!r}")

        self._store.save_reputation(updated)
        return updated

    # ── Selection score (Stage 3 catalog ranking) ─

    def selection_score(self, doc: AgentReputationDocument) -> float:
        """
        Adjusted score for Director catalog search (§4.3.2).
        SUSPENDED/RETIRED  → 0.0  (Director will not recruit)
        SCORE_REVIEW       → 0.7× (still usable; ranks lower)
        ACTIVE             → raw reputation_score
        """
        if doc.status in (AgentStatus.SUSPENDED, AgentStatus.RETIRED):
            return 0.0
        if doc.status == AgentStatus.SCORE_REVIEW:
            return doc.reputation_score * 0.7
        return doc.reputation_score