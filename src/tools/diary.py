"""Persisted daily views, explicit owner input, and operational error evidence."""

from datetime import date, datetime
from uuid import uuid4

from src.config import Settings
from src.domain.diary import (
    DiaryAppendResult,
    DiaryConfirmation,
    DiaryEvent,
    DiaryRecord,
    DiaryView,
    build_diary_view,
    diary_id,
)
from src.tools.audit import append_diary_record, get_diary_record, list_audit_entries


def read_diary_view(
    business_id: str, entry_date: date, *, as_of: datetime, settings: Settings
) -> DiaryView:
    filed = get_diary_record(business_id, diary_id(entry_date), settings)
    if filed is None:
        raise ValueError("No diary found for that business and date.")
    confirmation = get_diary_record(business_id, diary_id(entry_date) + "#confirmed", settings)
    if confirmation is not None and confirmation.timestamp > as_of:
        confirmation = None
    return build_diary_view(
        filed, confirmation, list_audit_entries(business_id, settings), as_of=as_of
    )


def confirm_diary(
    business_id: str,
    entry_date: date,
    answers: DiaryConfirmation,
    *,
    now: datetime,
    settings: Settings,
) -> DiaryAppendResult:
    return append_diary_record(
        DiaryRecord(
            entry_id=diary_id(entry_date) + "#confirmed",
            business_id=business_id,
            entry_date=entry_date,
            timestamp=now,
            event=DiaryEvent.CONFIRMED,
            confirmation=answers,
        ),
        settings,
    )


def record_diary_error(
    business_id: str, entry_date: date, error: Exception, *, now: datetime, settings: Settings
) -> None:
    """Store only the failure class, never raw exception text or user input."""
    append_diary_record(
        DiaryRecord(
            entry_id=diary_id(entry_date) + "#error#" + uuid4().hex,
            business_id=business_id,
            entry_date=entry_date,
            timestamp=now,
            event=DiaryEvent.ERROR,
            error_type=type(error).__name__,
        ),
        settings,
    )
