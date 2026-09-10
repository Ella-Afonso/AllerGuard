"""Shared offline audit fixtures and synthetic proposals; no duplicated café."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from moto import mock_aws

from src.agents.matcher import match_alert
from src.config import Settings
from src.domain.models import Alert, BusinessProfile, MatcherProposal, MatchResult
from src.domain.tiers import deterministic_floor
from src.tools.audit import ensure_audit_table

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


@pytest.fixture
def audit_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """No real account, credentials, or Bedrock needed for these tests."""
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    with mock_aws():
        settings = Settings(
            aws_region="eu-west-2",
            bedrock_model_id="offline-test-model",
            dynamodb_table_audit="allerguard-audit-test",
        )
        ensure_audit_table(settings)
        yield settings


def offline_assessor(alert: Alert, business: BusinessProfile) -> MatchResult:
    """Exercise actual Matcher validation with a clearly injected proposal."""
    floor = deterministic_floor(alert, business)
    return match_alert(
        alert,
        business,
        injected_proposal=MatcherProposal(
            proposed_tier=floor.tier,
            reason=floor.reason,
            evidence_refs=[candidate.candidate_id for candidate in floor.candidates],
        ),
    )
