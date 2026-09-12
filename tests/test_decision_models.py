"""Owner choice and notification evidence cannot contradict their event types."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from src.domain.models import (
    ActionPack,
    AuditEntry,
    AuditEvent,
    DecisionRecord,
    EscalationStatus,
    EscalationView,
    NotificationMode,
    NotificationOutcome,
    NotificationProvider,
    NotificationReceipt,
    OwnerDecision,
)
from tests.audit_support import NOW
from tests.test_audit import entry
from tests.test_escalation_queue import row


def choice(decision: OwnerDecision = OwnerDecision.APPROVE) -> DecisionRecord:
    original = row()
    return DecisionRecord(
        business_id=original.business_id,
        escalation_id=original.escalation_id,
        assessment_id=original.assessment_id,
        decision=decision,
        decided_at=NOW,
        original_action_pack=original.action_pack,
        edited_pack=original.action_pack if decision is OwnerDecision.EDIT else None,
    )


def notification(**changes: object) -> NotificationReceipt:
    data: dict[str, object] = {
        "business_id": "demo-cafe",
        "escalation_id": row().assessment_id,
        "outcome": "accepted",
        "provider": "stub",
        "mode": "simulated",
        "attempted_at": NOW,
        "message_id": "simulated-1",
    }
    data.update(changes)
    return NotificationReceipt.model_validate(data)


def queued_evidence() -> AuditEntry:
    original = row()
    return AuditEntry(
        entry_id=f"{original.assessment_id}#escalation_queued",
        assessment_id=original.assessment_id,
        timestamp=NOW,
        business_id=original.business_id,
        alert_id=original.alert_id,
        alert_modified=original.alert_modified,
        alert_title=original.alert_title,
        source_url=original.source_url,
        event=AuditEvent.ESCALATION_QUEUED,
        tier=original.tier,
        floor_tier=original.floor_tier,
        decision="escalate",
        reason=original.reason,
        policy_version=original.policy_version,
        model_id="injected-proposal",
        mode="injected",
        draft_source=original.draft_source,
    )


@pytest.mark.parametrize(
    ("decision", "status"),
    [
        (OwnerDecision.APPROVE, EscalationStatus.APPROVED),
        (OwnerDecision.EDIT, EscalationStatus.EDITED),
        (OwnerDecision.DECLINE, EscalationStatus.DECLINED),
    ],
)
def test_choice_projects_status_without_changing_queue(
    decision: OwnerDecision, status: EscalationStatus
) -> None:
    original = row()
    view = EscalationView(escalation=original, decision_record=choice(decision))
    assert view.effective_status is status
    assert original.status is EscalationStatus.PENDING
    assert EscalationView(escalation=original).effective_status is EscalationStatus.PENDING


@pytest.mark.parametrize(
    "changes",
    [
        {"decision": "edit"},
        {"edited_pack": row().action_pack.model_dump()},
        {"decision": "decline", "edited_pack": row().action_pack.model_dump()},
        {"escalation_id": "wrong"},
        {"assessment_id": "f" * 64},
        {"decided_at": NOW.replace(tzinfo=None)},
        {"business_id": "   "},
    ],
)
def test_invalid_choice_is_rejected(changes: dict[str, object]) -> None:
    raw = choice().model_dump()
    raw.update(changes)
    with pytest.raises(ValidationError):
        DecisionRecord.model_validate(raw)


@pytest.mark.parametrize("pull", [" ", "x" * 801])
def test_constructed_pack_does_not_bypass_validation(pull: str) -> None:
    bypass = row().action_pack.model_copy(update={"pull": pull})
    with pytest.raises(ValidationError):
        DecisionRecord(**(choice().model_dump() | {"decision": "edit", "edited_pack": bypass}))


@pytest.mark.parametrize(
    "changes",
    [
        {"message_id": None},
        {"failure_type": "UnexpectedError"},
        {"provider": "ses"},
        {"attempted_at": None},
        {"attempted_at": NOW.replace(tzinfo=None)},
        {"mode": "disabled"},
        {"provider": "log", "mode": "live"},
        {"outcome": "failed"},
        {"outcome": "unknown", "message_id": None, "failure_type": "secret@email.example"},
    ],
)
def test_notification_cannot_invent_acceptance(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        notification(**changes)


def test_disabled_and_unknown_are_distinct_from_success() -> None:
    disabled = notification(
        outcome=NotificationOutcome.DISABLED,
        mode=NotificationMode.DISABLED,
        provider=NotificationProvider.NONE,
        attempted_at=None,
        message_id=None,
    )
    assert disabled.attempted_at is None
    unknown = notification(outcome="unknown", message_id=None, failure_type="TransportError")
    assert unknown.outcome is NotificationOutcome.UNKNOWN


def test_old_audit_payload_is_still_readable() -> None:
    raw = entry().model_dump()
    raw.pop("notification")
    raw.pop("owner_decision")
    assert AuditEntry.model_validate(raw) == entry()


@pytest.mark.parametrize("error", [False, True])
def test_notification_can_retain_assessed_or_unassessed_queue(error: bool) -> None:
    raw = queued_evidence().model_dump()
    raw.update(
        event="notification_sent",
        entry_id=f"{row().assessment_id}#notification_sent",
        notification=notification(),
    )
    if error:
        raw.update(
            tier=None, floor_tier=None, error_type="MatcherModelError", draft_source="fallback"
        )
    result = AuditEntry.model_validate(raw)
    assert result.tier == (None if error else row().tier)
    assert result.notification is not None
    assert result.notification.failure_type is None


@pytest.mark.parametrize(
    "changes",
    [
        {"notification": None},
        {"notification": notification(outcome="failed", message_id=None, failure_type="Rejected")},
        {"notification": notification(business_id="another-business")},
        {"notification": notification(attempted_at=NOW + timedelta(seconds=1))},
        {"owner_decision": choice()},
    ],
)
def test_notification_event_requires_matching_payload(changes: dict[str, object]) -> None:
    raw = queued_evidence().model_dump() | {
        "event": "notification_sent",
        "entry_id": f"{row().assessment_id}#notification_sent",
        "notification": notification(),
    }
    with pytest.raises(ValidationError):
        AuditEntry.model_validate(raw | changes)


def test_choice_event_requires_its_own_payload_and_timestamp() -> None:
    raw = queued_evidence().model_dump() | {
        "event": "decision_recorded",
        "entry_id": f"{row().assessment_id}#decision_recorded",
        "owner_decision": choice(),
    }
    assert AuditEntry.model_validate(raw).owner_decision == choice()
    for changes in (
        {"owner_decision": None},
        {"timestamp": NOW + timedelta(seconds=1)},
        {"notification": notification()},
    ):
        with pytest.raises(ValidationError):
            AuditEntry.model_validate(raw | changes)


def test_match_event_cannot_retain_owner_payload() -> None:
    with pytest.raises(ValidationError):
        AuditEntry.model_validate(entry().model_dump() | {"owner_decision": choice()})


def test_original_and_edited_packs_stay_separate() -> None:
    revised = ActionPack(**(row().action_pack.model_dump() | {"pull": "Owner's revised draft."}))
    decision = choice(OwnerDecision.EDIT).model_dump() | {"edited_pack": revised}
    record = DecisionRecord.model_validate(decision)
    assert record.original_action_pack != record.edited_pack
