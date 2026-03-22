"""
anti_gaming.py
Anti-Gaming Detection Engine (§6.8.2).

Four mechanisms:
  1. Score weighting by build complexity     → complexity_weight in scorer.py
  2. Publisher identity verification         → AzureADVerifier
  3. Anomaly detection on score velocity     → VelocityDetector
  4. Community reports with 30-day window    → CommunityReportHandler
  +  Human audit resolution                 → AuditResolver
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Protocol

from .schemas import AgentReputationDocument, AgentStatus

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

class AntiGamingConfig:
    VELOCITY_WINDOW_HOURS:    int   = 24
    MAX_BUILDS_PER_WINDOW:    int   = 10
    SIMILAR_OWNER_THRESHOLD:  float = 0.80
    SCORE_SPIKE_THRESHOLD:    float = 0.15
    REPORT_WINDOW_DAYS:       int   = 30
    REPORTS_FOR_AUTO_SUSPEND: int   = 3


# ──────────────────────────────────────────────
# Store protocol
# ──────────────────────────────────────────────

class ReputationStore(Protocol):
    def get_recent_engagements(self, agent_id: str, since: datetime) -> List[dict]: ...
    def get_reporter_ids_in_window(self, agent_id: str, since: datetime) -> List[str]: ...
    def save_reputation(self, doc: AgentReputationDocument) -> None: ...


# ──────────────────────────────────────────────
# 1. Publisher identity verification
# ──────────────────────────────────────────────

@dataclass
class VerificationResult:
    is_verified: bool
    reason:      str


class AzureADVerifier:
    """
    Confirms the publishing Azure AD account is not a throwaway.
    Production: calls Microsoft Graph to check account age and risk signals.
    """
    MIN_ACCOUNT_AGE_DAYS: int = 30
    MIN_PRIOR_BUILDS:     int = 1

    def verify(self, azure_ad_id: str, account_age_days: int, prior_builds: int) -> VerificationResult:
        if account_age_days < self.MIN_ACCOUNT_AGE_DAYS:
            return VerificationResult(False,
                f"Account too new ({account_age_days}d < {self.MIN_ACCOUNT_AGE_DAYS}d required)")
        if prior_builds < self.MIN_PRIOR_BUILDS:
            return VerificationResult(False, "Publisher has no prior builds on the platform")
        return VerificationResult(True, "OK")


# ──────────────────────────────────────────────
# 2. Velocity anomaly detector
# ──────────────────────────────────────────────

@dataclass
class VelocityAnalysis:
    is_anomalous:        bool
    builds_in_window:    int
    same_owner_fraction: float
    score_delta:         float
    reason:              Optional[str] = None


class VelocityDetector:
    """
    Detects two patterns (§6.8.2):
      A) Build-farm: many builds in short window, mostly from same owner tenant.
      B) Score spike: score jumped > SCORE_SPIKE_THRESHOLD in one update.
    """

    def __init__(self, store: ReputationStore, cfg: AntiGamingConfig = None):
        self._store = store
        self._cfg   = cfg or AntiGamingConfig()

    def analyse(self, doc: AgentReputationDocument, new_score: float, old_score: float) -> VelocityAnalysis:
        since  = datetime.now(timezone.utc) - timedelta(hours=self._cfg.VELOCITY_WINDOW_HOURS)
        recent = self._store.get_recent_engagements(doc.agent_id, since)
        n      = len(recent)

        same_owner_fraction = 0.0
        if n > 0:
            prefix = doc.publisher_azure_ad[:8]
            same   = sum(1 for r in recent if r.get("owner_azure_ad_id", "")[:8] == prefix)
            same_owner_fraction = same / n

        delta = abs(new_score - old_score)

        if n > self._cfg.MAX_BUILDS_PER_WINDOW and same_owner_fraction >= self._cfg.SIMILAR_OWNER_THRESHOLD:
            return VelocityAnalysis(True, n, same_owner_fraction, delta,
                f"Build-farm: {n} builds in {self._cfg.VELOCITY_WINDOW_HOURS}h, "
                f"{same_owner_fraction:.0%} same-tenant.")

        if delta > self._cfg.SCORE_SPIKE_THRESHOLD:
            return VelocityAnalysis(True, n, same_owner_fraction, delta,
                f"Score spike: +{delta:.3f} (threshold {self._cfg.SCORE_SPIKE_THRESHOLD}).")

        return VelocityAnalysis(False, n, same_owner_fraction, delta)

    def apply_flag(self, doc: AgentReputationDocument, analysis: VelocityAnalysis) -> AgentReputationDocument:
        """Sets 'Score Under Review' badge. Agent remains usable (§6.8.2)."""
        if not analysis.is_anomalous:
            return doc
        logger.warning("VELOCITY FLAG agent=%s reason=%s", doc.agent_id, analysis.reason)
        now = datetime.now(timezone.utc)
        return doc.model_copy(update={
            "status": AgentStatus.SCORE_REVIEW,
            "anti_gaming": doc.anti_gaming.model_copy(update={
                "score_under_review":  True,
                "review_reason":       analysis.reason,
                "review_triggered_at": now,
            }),
        })


# ──────────────────────────────────────────────
# 3. Community report handler
# ──────────────────────────────────────────────

@dataclass
class ReportResult:
    accepted:        bool
    total_in_window: int
    auto_suspended:  bool
    message:         str


class CommunityReportHandler:
    """
    Rolling 30-day window. 3 independent reporter IDs → auto-suspend.
    Same reporter filing again within the window does not count.
    """

    def __init__(self, cfg: AntiGamingConfig = None):
        self._cfg = cfg or AntiGamingConfig()

    def file_report(
        self,
        doc:                  AgentReputationDocument,
        reporter_azure_ad_id: str,
        prior_reporter_ids:   List[str],
    ) -> tuple[AgentReputationDocument, ReportResult]:

        now   = datetime.now(timezone.utc)
        flags = doc.anti_gaming

        window_expired = (
            flags.last_report_window_start is None
            or (now - flags.last_report_window_start) > timedelta(days=self._cfg.REPORT_WINDOW_DAYS)
        )
        if window_expired:
            flags              = flags.model_copy(update={"community_report_count": 0, "last_report_window_start": now})
            prior_reporter_ids = []

        if reporter_azure_ad_id in prior_reporter_ids:
            return doc, ReportResult(False, flags.community_report_count, False,
                "Not counted: same reporter already filed within the 30-day window.")

        new_count      = flags.community_report_count + 1
        auto_suspended = new_count >= self._cfg.REPORTS_FOR_AUTO_SUSPEND
        new_status     = AgentStatus.SUSPENDED if auto_suspended else doc.status
        flags          = flags.model_copy(update={"community_report_count": new_count})

        if auto_suspended:
            logger.warning("AUTO-SUSPEND agent=%s reports=%d", doc.agent_id, new_count)
            flags = flags.model_copy(update={
                "score_under_review":  True,
                "review_reason":       f"Auto-suspended: {new_count} reports in 30-day window.",
                "review_triggered_at": now,
            })

        updated = doc.model_copy(update={"status": new_status, "anti_gaming": flags, "last_updated_at": now})
        msg = ("Agent auto-suspended pending audit." if auto_suspended
               else f"Report filed ({new_count}/{self._cfg.REPORTS_FOR_AUTO_SUSPEND} for auto-suspend).")
        return updated, ReportResult(True, new_count, auto_suspended, msg)


# ──────────────────────────────────────────────
# 4. Human audit resolution
# ──────────────────────────────────────────────

class AuditResolver:

    @staticmethod
    def clear_and_restore(doc: AgentReputationDocument, auditor: str, notes: str) -> AgentReputationDocument:
        now = datetime.now(timezone.utc)
        return doc.model_copy(update={
            "status":          AgentStatus.ACTIVE,
            "last_updated_at": now,
            "anti_gaming":     doc.anti_gaming.model_copy(update={
                "score_under_review":       False,
                "review_reason":            f"Cleared by {auditor}: {notes}",
                "review_triggered_at":      now,
                "community_report_count":   0,
                "last_report_window_start": now,
            }),
        })

    @staticmethod
    def retire(doc: AgentReputationDocument, auditor: str, notes: str) -> AgentReputationDocument:
        now = datetime.now(timezone.utc)
        return doc.model_copy(update={
            "status":          AgentStatus.RETIRED,
            "last_updated_at": now,
            "anti_gaming":     doc.anti_gaming.model_copy(update={
                "review_reason":       f"Retired by {auditor}: {notes}",
                "review_triggered_at": now,
            }),
        })