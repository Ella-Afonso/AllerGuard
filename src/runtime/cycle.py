"""Trusted batch orchestration for one configured business and a serial ledger."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from src.config import Settings
from src.domain.cycle import AlertOutcome, CycleAlertResult, CycleReport, CycleStatus
from src.domain.models import (
    AuditEvent,
    BusinessProfile,
    GateDecision,
    NotificationOutcome,
    ProcessedAlert,
)
from src.runtime.notification import DeliveryFunction
from src.runtime.process_alert import AssessmentFunction, DrafterFunction, process_alert
from src.tools import alert_ledger
from src.tools.audit import get_audit_entry
from src.tools.escalation_queue import get_decision

logger = logging.getLogger(__name__)


class IncompleteOutcomeError(RuntimeError):
    """The returned processing receipt lacks required persisted evidence."""


def _completed_outcome(receipt: ProcessedAlert, settings: Settings) -> AlertOutcome:
    entry = receipt.audit.entry
    if receipt.decision is GateDecision.SILENT:
        return AlertOutcome.SILENT
    if receipt.escalation is None or receipt.queue_audit is None:
        raise IncompleteOutcomeError("Escalation requires queue and audit evidence.")
    # An explicit owner choice ends notification work, but its audit must exist.
    decision = get_decision(entry.business_id, entry.assessment_id, settings)
    if decision is not None:
        if (
            get_audit_entry(entry.business_id, f"{entry.assessment_id}#decision_recorded", settings)
            is None
        ):
            raise IncompleteOutcomeError("Owner decision requires audit repair.")
    else:
        # Read stored outcomes instead of trusting an attempted sender result.
        sent = get_audit_entry(
            entry.business_id, f"{entry.assessment_id}#notification_sent", settings
        )
        unknown = get_audit_entry(
            entry.business_id, f"{entry.assessment_id}#notification_unknown", settings
        )
        failed = get_audit_entry(
            entry.business_id, f"{entry.assessment_id}#notification_failed", settings
        )
        if sent is not None:
            if (
                sent.notification is None
                or sent.notification.outcome is not NotificationOutcome.ACCEPTED
            ):
                raise IncompleteOutcomeError("Stored acceptance is invalid.")
        elif unknown is not None or failed is not None:
            raise IncompleteOutcomeError("Notification requires reconciliation or retry.")
        elif settings.notification_mode != "disabled":
            raise IncompleteOutcomeError("Enabled notification has no persisted acceptance.")
    return (
        AlertOutcome.HANDLED_ERROR
        if entry.event is AuditEvent.MATCH_ERROR
        else AlertOutcome.ESCALATED
    )


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def run_monitoring_cycle(
    business: BusinessProfile,
    *,
    settings: Settings | None = None,
    assessor: AssessmentFunction | None = None,
    drafter: DrafterFunction | None = None,
    notifier: DeliveryFunction | None = None,
) -> CycleReport:
    """Process the full retrieved batch; only code can authorize a ledger commit.

    Call serially with one business per ledger. No owner choice is generated here.
    Persistence failures block the batch; they cannot guarantee an audit write.
    A commit exception may follow partial writes, so its outcome is uncertain.
    """
    resolved = settings or Settings.from_environment()
    started = datetime.now(UTC)
    identity = str(uuid4())
    before: str | None = None
    after: str | None = None
    rows: list[CycleAlertResult] = []

    def finish(status: CycleStatus, error: str | None = None) -> CycleReport:
        result = CycleReport(
            cycle_id=identity,
            business_id=business.business_id,
            started_at=started,
            finished_at=datetime.now(UTC),
            status=status,
            alerts=tuple(rows),
            watermark_before=_time(before),
            watermark_after=_time(after),
            error_type=error,
        )
        logger.info(
            "monitoring_cycle cycle=%s status=%s retrieved=%d blocked=%d",
            identity,
            status.value,
            result.retrieved,
            result.blocked,
        )
        return result

    try:
        before = alert_ledger.read_alert_watermark(resolved)
        after = before
        alerts = alert_ledger.load_new_alerts(resolved)
    except Exception as error:
        return finish(CycleStatus.BLOCKED, type(error).__name__[:80])
    if not alerts:
        return finish(CycleStatus.EMPTY)
    for alert in alerts:
        assessment: str | None = None
        try:
            receipt = process_alert(
                alert,
                business,
                timestamp=datetime.now(UTC),
                settings=resolved,
                assessor=assessor,
                drafter=drafter,
                notifier=notifier,
            )
            assessment = receipt.audit.entry.assessment_id
            outcome = _completed_outcome(receipt, resolved)
            rows.append(
                CycleAlertResult(
                    alert_id=alert.id,
                    modified=alert.modified,
                    outcome=outcome,
                    assessment_id=assessment,
                    error_type=receipt.audit.entry.error_type,
                )
            )
        except Exception as error:
            rows.append(
                CycleAlertResult(
                    alert_id=alert.id,
                    modified=alert.modified,
                    outcome=AlertOutcome.BLOCKED,
                    assessment_id=assessment,
                    error_type=type(error).__name__[:80],
                )
            )
            logger.error(
                "cycle_alert_blocked alert=%s error_type=%s", alert.id, type(error).__name__
            )
    if any(row.outcome is AlertOutcome.BLOCKED for row in rows):
        return finish(CycleStatus.BLOCKED)
    target = max(alert.modified for alert in alerts).astimezone(UTC).isoformat()
    try:
        alert_ledger.commit_processed_batch(target, alerts, resolved)
        after = alert_ledger.read_alert_watermark(resolved)
        if after is None or datetime.fromisoformat(after) < datetime.fromisoformat(target):
            raise IncompleteOutcomeError("Committed watermark read-back does not cover the batch.")
    except Exception as error:
        # Do not label the pre-commit value as a post-commit read-back.
        after = None
        return finish(CycleStatus.COMMIT_UNKNOWN, type(error).__name__[:80])
    return finish(CycleStatus.COMMITTED)
