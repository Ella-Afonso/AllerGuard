"""Runtime orchestration for owner notification and notification audit facts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from src.config import Settings
from src.domain.models import (
    AuditAppendResult,
    AuditEntry,
    AuditEvent,
    Escalation,
    GateDecision,
    NotificationMode,
    NotificationOutcome,
    NotificationReceipt,
)
from src.tools import audit
from src.tools.escalation_queue import get_decision, get_escalation, get_queued_evidence
from src.tools.notify import notify_owner

DeliveryFunction = Callable[[Escalation, Settings, datetime], NotificationReceipt]


class NotificationPersistenceError(RuntimeError):
    """A notification outcome could not be durably acknowledged."""


def _check_queued_evidence(escalation: Escalation, queued_audit: AuditEntry) -> None:
    """Reject a caller-provided queue receipt that is not the stored queue fact."""
    if queued_audit.event is not AuditEvent.ESCALATION_QUEUED:
        raise NotificationPersistenceError("Notification requires queued-audit evidence.")
    if (
        queued_audit.business_id != escalation.business_id
        or queued_audit.assessment_id != escalation.assessment_id
        or queued_audit.alert_id != escalation.alert_id
        or queued_audit.draft_source is not escalation.draft_source
    ):
        raise NotificationPersistenceError("Queued-audit evidence does not match the escalation.")


def _notification_event(receipt: NotificationReceipt) -> AuditEvent:
    return {
        NotificationOutcome.ACCEPTED: AuditEvent.NOTIFICATION_SENT,
        NotificationOutcome.FAILED: AuditEvent.NOTIFICATION_FAILED,
        NotificationOutcome.UNKNOWN: AuditEvent.NOTIFICATION_UNKNOWN,
    }[receipt.outcome]


def _append_notification_audit(
    escalation: Escalation,
    queued_audit: AuditEntry,
    receipt: NotificationReceipt,
    settings: Settings,
) -> AuditAppendResult:
    """Append one event keyed by the assessment and outcome kind."""
    event = _notification_event(receipt)
    return audit.append_audit_entry(
        AuditEntry.model_validate(
            queued_audit.model_dump(mode="python")
            | {
                "entry_id": f"{escalation.assessment_id}#{event.value}",
                "event": event,
                "timestamp": receipt.attempted_at,
                "notification": receipt,
                "owner_decision": None,
                "decision": GateDecision.ESCALATE,
            }
        ),
        settings,
    )


def notify_escalation(
    escalation: Escalation,
    settings: Settings,
    attempted_at: datetime,
    *,
    queued_audit: AuditEntry | None = None,
    delivery: DeliveryFunction | None = None,
) -> NotificationReceipt | None:
    """Deliver an eligible queued escalation and persist its outcome.

    A stored SENT or UNKNOWN event is returned without another provider call.
    FAILED is eligible for a later explicit retry. This serial read-before-send
    check does not close the crash/concurrency window between provider acceptance
    and its audit append; no exactly-once external-delivery claim is made.
    """
    if attempted_at.tzinfo is None or attempted_at.utcoffset() is None:
        raise ValueError("attempted_at must include a timezone.")
    stored = get_escalation(escalation.business_id, escalation.escalation_id, settings)
    if stored is None:
        raise NotificationPersistenceError("Notification requires a stored queue row.")
    if (
        stored.assessment_id != escalation.assessment_id
        or stored.alert_id != escalation.alert_id
        or stored.business_id != escalation.business_id
    ):
        raise NotificationPersistenceError("Caller escalation does not match the stored queue.")
    stored_evidence = get_queued_evidence(stored, settings)
    if queued_audit is not None:
        _check_queued_evidence(stored, queued_audit)
        if queued_audit.entry_id != stored_evidence.entry_id:
            raise NotificationPersistenceError("Caller queued-audit is not the stored evidence.")
    queued_audit = stored_evidence
    escalation = stored

    stored_decision = get_decision(escalation.business_id, escalation.escalation_id, settings)
    if stored_decision is not None:
        return None

    sent = audit.get_audit_entry(
        escalation.business_id,
        f"{escalation.assessment_id}#{AuditEvent.NOTIFICATION_SENT.value}",
        settings,
    )
    if sent is not None:
        if sent.notification is None:
            raise NotificationPersistenceError("Stored notification event has no receipt.")
        return sent.notification
    unknown = audit.get_audit_entry(
        escalation.business_id,
        f"{escalation.assessment_id}#{AuditEvent.NOTIFICATION_UNKNOWN.value}",
        settings,
    )
    if unknown is not None:
        if unknown.notification is None:
            raise NotificationPersistenceError("Stored unknown event has no receipt.")
        return unknown.notification

    if settings.notification_mode == "disabled":
        return None

    sender = delivery or notify_owner
    receipt = sender(escalation, settings, attempted_at)
    if receipt.outcome is NotificationOutcome.DISABLED:
        if receipt.mode is not NotificationMode.DISABLED:
            raise NotificationPersistenceError("Disabled receipt has contradictory mode.")
        return None
    receipt_time = receipt.attempted_at
    if receipt_time is None or (
        receipt.business_id != escalation.business_id
        or receipt.escalation_id != escalation.escalation_id
        or receipt_time != attempted_at.astimezone(receipt_time.tzinfo)
    ):
        raise NotificationPersistenceError("Delivery receipt identity or time does not match.")
    if receipt.mode is NotificationMode.DISABLED:
        raise NotificationPersistenceError("Attempted delivery cannot use disabled mode.")
    _append_notification_audit(escalation, queued_audit, receipt, settings)
    return receipt


# Descriptive alias for callers that prefer an imperative name.
send_owner_notification = notify_escalation
