"""Offline orchestration tests with simulated provider receipts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.config import Settings
from src.domain.models import (
    NotificationMode,
    NotificationOutcome,
    NotificationProvider,
    NotificationReceipt,
    OwnerDecision,
)
from src.runtime import notification as notification_runtime
from src.runtime.notification import notify_escalation
from src.tools import audit
from src.tools.escalation_queue import list_pending, record_decision
from tests.test_approve_cli import _queue_with_audit

NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def _live_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "notification_mode": "ses",
            "ses_from_email": "owner@example.test",
            "owner_email": "owner@example.test",
        }
    )


def _receipt(escalation, outcome: NotificationOutcome, *, suffix: str) -> NotificationReceipt:
    return NotificationReceipt(
        business_id=escalation.business_id,
        escalation_id=escalation.escalation_id,
        outcome=outcome,
        provider=NotificationProvider.STUB,
        mode=NotificationMode.SIMULATED,
        attempted_at=NOW,
        message_id=f"sim-{suffix}" if outcome is NotificationOutcome.ACCEPTED else None,
        failure_type=None if outcome is NotificationOutcome.ACCEPTED else outcome.value,
    )


def test_disabled_skips_delivery_and_writes_no_notification(audit_settings) -> None:
    escalation = _queue_with_audit(audit_settings)
    calls: list[str] = []

    def delivery(*args):
        calls.append("called")
        raise AssertionError("disabled mode must not call delivery")

    assert notify_escalation(escalation, audit_settings, NOW, delivery=delivery) is None
    assert calls == []
    assert len(audit.list_audit_entries("demo-cafe", audit_settings)) == 1


def test_simulated_success_is_audited_and_replay_does_not_send_again(audit_settings) -> None:
    settings = _live_settings(audit_settings)
    escalation = _queue_with_audit(settings)
    calls = 0

    def delivery(item, configured, attempted_at):
        nonlocal calls
        calls += 1
        return _receipt(item, NotificationOutcome.ACCEPTED, suffix="one")

    first = notify_escalation(escalation, settings, NOW, delivery=delivery)
    second = notify_escalation(escalation, settings, NOW, delivery=delivery)
    assert first is not None and first.outcome is NotificationOutcome.ACCEPTED
    assert second == first
    assert calls == 1
    assert len(audit.list_audit_entries("demo-cafe", settings)) == 2


def test_definite_failure_can_be_retried_and_success_is_retained(audit_settings) -> None:
    settings = _live_settings(audit_settings)
    escalation = _queue_with_audit(settings)
    outcomes = iter((NotificationOutcome.FAILED, NotificationOutcome.ACCEPTED))

    def delivery(item, configured, attempted_at):
        return _receipt(item, next(outcomes), suffix="retry")

    failed = notify_escalation(escalation, settings, NOW, delivery=delivery)
    succeeded = notify_escalation(escalation, settings, NOW, delivery=delivery)
    events = audit.list_audit_entries("demo-cafe", settings)
    assert failed is not None and failed.outcome is NotificationOutcome.FAILED
    assert succeeded is not None and succeeded.outcome is NotificationOutcome.ACCEPTED
    assert {event.event.value for event in events} == {
        "escalation_queued",
        "notification_failed",
        "notification_sent",
    }
    assert len(list_pending("demo-cafe", settings)) == 1


def test_unknown_outcome_is_visible_and_not_automatically_resent(audit_settings) -> None:
    settings = _live_settings(audit_settings)
    escalation = _queue_with_audit(settings)
    calls = 0

    def delivery(item, configured, attempted_at):
        nonlocal calls
        calls += 1
        return _receipt(item, NotificationOutcome.UNKNOWN, suffix="unknown")

    first = notify_escalation(escalation, settings, NOW, delivery=delivery)
    second = notify_escalation(escalation, settings, NOW, delivery=delivery)
    assert first is not None and first.outcome is NotificationOutcome.UNKNOWN
    assert second == first
    assert calls == 1


def test_owner_choice_suppresses_later_notification(audit_settings) -> None:
    settings = _live_settings(audit_settings)
    escalation = _queue_with_audit(settings)
    record_decision(
        escalation.business_id,
        escalation.escalation_id,
        OwnerDecision.DECLINE,
        decided_at=NOW,
        settings=settings,
    )
    assert (
        notify_escalation(
            escalation,
            settings,
            NOW,
            delivery=lambda *args: pytest.fail("decided escalation must not notify"),
        )
        is None
    )


def test_notification_audit_failure_does_not_remove_pending_queue(
    audit_settings, monkeypatch
) -> None:
    settings = _live_settings(audit_settings)
    escalation = _queue_with_audit(settings)

    def fail(*args, **kwargs):
        raise audit.AuditPersistenceError("synthetic audit outage")

    monkeypatch.setattr(audit, "append_audit_entry", fail)
    with pytest.raises(audit.AuditPersistenceError, match="synthetic audit outage"):
        notify_escalation(
            escalation,
            settings,
            NOW,
            delivery=lambda item, configured, attempted_at: _receipt(
                item, NotificationOutcome.ACCEPTED, suffix="unacknowledged"
            ),
        )
    assert len(list_pending("demo-cafe", settings)) == 1


def test_missing_queued_audit_is_rejected_before_delivery(audit_settings, monkeypatch) -> None:
    escalation = _queue_with_audit(audit_settings, 7)

    def missing(*args, **kwargs):
        raise audit.AuditPersistenceError("synthetic missing queued audit")

    monkeypatch.setattr(notification_runtime, "get_queued_evidence", missing)
    with pytest.raises(audit.AuditPersistenceError, match="synthetic missing queued audit"):
        notify_escalation(
            escalation,
            _live_settings(audit_settings),
            NOW,
            delivery=lambda *args: pytest.fail("delivery must wait for queued audit"),
        )
