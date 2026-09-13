"""Schedulable daily filing; persistence and evidence retrieval remain in tools."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from typing import Sequence

from src.agents.diary import SummaryPolisher, polish_diary
from src.config import Settings
from src.domain.diary import DiaryAppendResult, DiaryEvent, DiaryRecord, build_diary_entry, diary_id
from src.tools import audit
from src.tools.diary import record_diary_error


def run_daily_diary(
    business_id: str,
    entry_date: date,
    *,
    now: datetime,
    settings: Settings,
    polisher: SummaryPolisher | None = None,
    model_id: str = "",
) -> DiaryAppendResult:
    """Read before generation; retry returns the persisted first filing."""
    existing = audit.get_diary_record(business_id, diary_id(entry_date), settings)
    if existing is not None:
        return DiaryAppendResult(record=existing, created=False)
    entries = audit.list_audit_entries(business_id, settings)
    try:
        diary = build_diary_entry(entry_date, business_id, entries, now=now)
        diary = polish_diary(diary, polisher, model_id=model_id)
    except Exception as error:
        record_diary_error(business_id, entry_date, error, now=now, settings=settings)
        raise
    return audit.append_diary_record(
        DiaryRecord(
            entry_id=diary_id(entry_date),
            business_id=business_id,
            entry_date=entry_date,
            timestamp=diary.filed_at,
            event=DiaryEvent.FILED,
            diary=diary,
        ),
        settings,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--business-id", required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_daily_diary(
            args.business_id, args.date, now=datetime.now(UTC), settings=Settings.from_environment()
        )
        print(f"Diary {'filed' if result.created else 'reused'}: {result.record.entry_id}")
        print("Use the diary show command to inspect any subsequent owner confirmation.")
        return 0
    except (ValueError, audit.AuditPersistenceError) as error:
        print(f"Diary filing failed: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
