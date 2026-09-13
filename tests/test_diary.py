"""Daily facts remain conservative, date-scoped, immutable and traceable."""

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.agents.diary import polish_diary
from src.domain.diary import (
    DailyStatus,
    DiaryConfirmation,
    DiaryEntry,
    DiaryEvent,
    DiaryRecord,
    build_diary_entry,
    build_diary_view,
    business_date,
    diary_id,
    recall_links,
)
from src.domain.models import AuditEntry, AuditEvent, DecisionRecord, OwnerDecision
from tests.audit_support import NOW
from tests.test_action_draft import _valid_pack
from tests.test_audit import queued_entry


def decision_entry(
    number: int = 1,
    *,
    when: datetime = NOW,
    business_id: str = "demo-cafe",
    decision: OwnerDecision = OwnerDecision.APPROVE,
) -> AuditEntry:
    queued = queued_entry(number)
    pack = _valid_pack()
    record = DecisionRecord(
        business_id=business_id,
        escalation_id=queued.assessment_id,
        assessment_id=queued.assessment_id,
        decision=decision,
        decided_at=when,
        original_action_pack=pack,
        edited_pack=pack if decision is OwnerDecision.EDIT else None,
    )
    return AuditEntry.model_validate(
        {
            **queued.model_dump(),
            "entry_id": f"{queued.assessment_id}#decision_recorded",
            "business_id": business_id,
            "timestamp": when,
            "event": AuditEvent.DECISION_RECORDED,
            "owner_decision": record,
        }
    )


def filed_record() -> DiaryRecord:
    diary = build_diary_entry(NOW.date(), "demo-cafe", [], now=NOW)
    return DiaryRecord(
        entry_id=diary_id(NOW.date()),
        business_id="demo-cafe",
        entry_date=NOW.date(),
        timestamp=NOW,
        event=DiaryEvent.FILED,
        diary=diary,
    )


def test_links_use_owner_date_business_and_preserve_choices() -> None:
    rows = [
        decision_entry(),
        decision_entry(2, when=NOW - timedelta(days=1)),
        decision_entry(3, business_id="another-cafe"),
        decision_entry(4, decision=OwnerDecision.EDIT),
        decision_entry(5, decision=OwnerDecision.DECLINE),
    ]
    diary = build_diary_entry(NOW.date(), "demo-cafe", rows, now=NOW)
    assert [link.state for link in diary.recall_actions] == ["approve", "edit", "decline"]
    assert diary.recall_actions[1].edited_pack == _valid_pack()
    assert diary.opening_status is DailyStatus.UNCONFIRMED
    assert diary.closing_status is DailyStatus.UNCONFIRMED
    assert "No physical action is inferred" in diary.summary


def test_pending_links_are_resolved_only_by_persisted_choices() -> None:
    queued = queued_entry()
    assert recall_links(NOW.date(), "demo-cafe", [queued], as_of=NOW)[0].state == "pending"
    linked = recall_links(NOW.date(), "demo-cafe", [queued, decision_entry()], as_of=NOW)
    assert len(linked) == 1 and linked[0].state == "approve"


def test_duplicate_evidence_is_not_repeated() -> None:
    row = decision_entry()
    assert len(recall_links(NOW.date(), "demo-cafe", [row, row], as_of=NOW)) == 1


def test_later_day_decision_cannot_rewrite_historical_pending_state() -> None:
    tomorrow = NOW + timedelta(days=1)
    rows = [queued_entry(), decision_entry(when=tomorrow)]
    historical = recall_links(NOW.date(), "demo-cafe", rows, as_of=tomorrow)
    assert len(historical) == 1 and historical[0].state == "pending"
    current = recall_links(tomorrow.date(), "demo-cafe", rows, as_of=tomorrow)
    assert len(current) == 1 and current[0].state == "approve"


@pytest.mark.parametrize(
    "instant, expected",
    [
        (datetime(2026, 9, 12, 23, 30, tzinfo=UTC), date(2026, 9, 13)),
        (datetime(2026, 1, 12, 23, 30, tzinfo=UTC), date(2026, 1, 12)),
        (datetime(2026, 3, 29, 0, 30, tzinfo=UTC), date(2026, 3, 29)),
        (datetime(2026, 10, 25, 1, 30, tzinfo=UTC), date(2026, 10, 25)),
    ],
)
def test_london_date(instant: datetime, expected: date) -> None:
    assert business_date(instant) == expected


def test_naive_or_future_dates_rejected() -> None:
    with pytest.raises(ValueError):
        business_date(datetime(2026, 9, 13))
    with pytest.raises(ValueError):
        build_diary_entry(NOW.date() + timedelta(days=1), "demo-cafe", [], now=NOW)


@pytest.mark.parametrize("field", ["temperature", "cleaning_rota", "probe_calibration"])
def test_scope_extras_rejected(field: str) -> None:
    diary = build_diary_entry(NOW.date(), "demo-cafe", [], now=NOW)
    with pytest.raises(ValidationError):
        DiaryEntry.model_validate({**diary.model_dump(), field: "invented"})


def test_confirmations_require_explicit_answers_and_exception_note() -> None:
    with pytest.raises(ValidationError):
        DiaryConfirmation(opening_status="unconfirmed", closing_status="confirmed")
    with pytest.raises(ValidationError):
        DiaryConfirmation(opening_status="exception", closing_status="confirmed", note="   ")
    assert DiaryConfirmation(
        opening_status="exception", closing_status="confirmed", note="Owner reported an exception."
    ).note


def test_original_filing_cannot_claim_confirmation() -> None:
    diary = filed_record().diary
    assert diary is not None
    with pytest.raises(ValidationError):
        DiaryEntry.model_validate({**diary.model_dump(), "opening_status": "confirmed"})


def test_late_link_projection_preserves_original_snapshot() -> None:
    filed = filed_record()
    later = NOW + timedelta(hours=1)
    view = build_diary_view(filed, None, [decision_entry(when=later)], as_of=later)
    assert view.filed == filed_record()
    assert view.filed.diary is not None and not view.filed.diary.recall_actions
    assert len(view.additional_links) == 1
    assert not build_diary_view(
        filed, None, [decision_entry(when=later)], as_of=NOW
    ).additional_links


@pytest.mark.parametrize("value", ["", " ", "x" * 1001, None])
def test_invalid_optional_polish_falls_back(value: object) -> None:
    diary = filed_record().diary
    assert diary is not None
    assert polish_diary(diary, lambda _: value, model_id="test") == diary  # type: ignore[arg-type,return-value]


def test_polish_failure_and_valid_provenance() -> None:
    diary = filed_record().diary
    assert diary is not None

    def unavailable(_: DiaryEntry) -> str:
        raise RuntimeError("Unavailable")

    assert polish_diary(diary, unavailable, model_id="test") == diary
    polished = polish_diary(diary, lambda _: "Owner confirmation is pending.", model_id="test")
    assert polished.summary_source.value == "model"
    assert polished.recall_actions == diary.recall_actions
    assert polished.opening_status == diary.opening_status
