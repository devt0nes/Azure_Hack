"""
test_anti_gaming.py — v2.
Run from repo root: pytest tests/ -v
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from src.schemas import AgentReputationDocument, AgentStatus
from src.anti_gaming import (
    AntiGamingConfig, AuditResolver, AzureADVerifier,
    CommunityReportHandler, VelocityDetector,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_doc(score=0.5, status=AgentStatus.ACTIVE, report_count=0, window_start=None):
    doc = AgentReputationDocument(agent_id="a1", agent_name="Test",
                                  publisher_azure_ad="org-aad-pub12345",
                                  reputation_score=score, status=status)
    if report_count or window_start:
        doc = doc.model_copy(update={"anti_gaming": doc.anti_gaming.model_copy(update={
            "community_report_count":   report_count,
            "last_report_window_start": window_start or datetime.now(timezone.utc),
        })})
    return doc

def mock_store(recent=None):
    s = MagicMock()
    s.get_recent_engagements.return_value = recent or []
    return s


# ── AzureADVerifier ───────────────────────────────────────────────────────────

def test_new_account_rejected():
    assert not AzureADVerifier().verify("u", 5, 3).is_verified

def test_no_prior_builds_rejected():
    assert not AzureADVerifier().verify("u", 60, 0).is_verified

def test_valid_account_passes():
    assert AzureADVerifier().verify("u", 60, 5).is_verified


# ── VelocityDetector ──────────────────────────────────────────────────────────

def test_no_anomaly_few_builds():
    assert not VelocityDetector(mock_store()).analyse(make_doc(), 0.6, 0.5).is_anomalous

def test_build_farm_flagged():
    records  = [{"owner_azure_ad_id": "org-aad-pub12345"} for _ in range(12)]
    result   = VelocityDetector(mock_store(records)).analyse(make_doc(), 0.65, 0.5)
    assert result.is_anomalous

def test_score_spike_flagged():
    result = VelocityDetector(mock_store()).analyse(make_doc(), 0.70, 0.50)
    assert result.is_anomalous

def test_flag_sets_review_status():
    records  = [{"owner_azure_ad_id": "org-aad-pub12345"} for _ in range(12)]
    detector = VelocityDetector(mock_store(records))
    doc      = make_doc()
    analysis = detector.analyse(doc, 0.65, 0.5)
    flagged  = detector.apply_flag(doc, analysis)
    assert flagged.status == AgentStatus.SCORE_REVIEW
    assert flagged.anti_gaming.score_under_review

def test_clean_analysis_unchanged():
    detector = VelocityDetector(mock_store())
    doc      = make_doc()
    analysis = detector.analyse(doc, 0.51, 0.50)
    assert detector.apply_flag(doc, analysis) is doc


# ── CommunityReportHandler ────────────────────────────────────────────────────

def test_first_report_accepted():
    _, r = CommunityReportHandler().file_report(make_doc(), "rep-001", [])
    assert r.accepted and r.total_in_window == 1 and not r.auto_suspended

def test_duplicate_not_counted():
    doc = make_doc(window_start=datetime.now(timezone.utc))
    _, r = CommunityReportHandler().file_report(doc, "rep-001", ["rep-001"])
    assert not r.accepted

def test_three_reports_auto_suspend():
    doc = make_doc(report_count=2)
    updated, r = CommunityReportHandler().file_report(doc, "rep-003", ["rep-001", "rep-002"])
    assert r.auto_suspended and updated.status == AgentStatus.SUSPENDED

def test_window_resets_after_expiry():
    old  = datetime.now(timezone.utc) - timedelta(days=31)
    doc  = make_doc(report_count=2, window_start=old)
    _, r = CommunityReportHandler().file_report(doc, "rep-new", [])
    assert r.total_in_window == 1


# ── AuditResolver ─────────────────────────────────────────────────────────────

def test_restore_clears():
    doc      = make_doc(status=AgentStatus.SUSPENDED)
    doc      = doc.model_copy(update={"anti_gaming": doc.anti_gaming.model_copy(update={"score_under_review": True})})
    restored = AuditResolver.clear_and_restore(doc, "admin", "clean")
    assert restored.status == AgentStatus.ACTIVE
    assert not restored.anti_gaming.score_under_review

def test_retire():
    retired = AuditResolver.retire(make_doc(status=AgentStatus.SUSPENDED), "admin", "malicious")
    assert retired.status == AgentStatus.RETIRED