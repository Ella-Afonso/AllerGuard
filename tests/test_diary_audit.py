"""Daily appends coexist with strict recall history and safe retries."""

from datetime import timedelta
from unittest.mock import patch

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError

from src.config import Settings
from src.domain.diary import DiaryConfirmation, DiaryEvent, DiaryRecord, diary_id
from src.runtime.daily_diary import run_daily_diary
from src.tools import audit
from src.tools.diary import confirm_diary
from tests.audit_support import NOW
from tests.test_audit import entry
from tests.test_diary import decision_entry, filed_record


def test_first_winners_and_original_preserved(audit_settings: Settings) -> None:
    first = run_daily_diary("demo-cafe", NOW.date(), now=NOW, settings=audit_settings)
    audit.append_audit_entry(decision_entry(when=NOW + timedelta(minutes=1)), audit_settings)
    with patch(
        "src.runtime.daily_diary.build_diary_entry", side_effect=AssertionError("regenerated")
    ):
        retry = run_daily_diary("demo-cafe", NOW.date(), now=NOW, settings=audit_settings)
    assert first.created and not retry.created and first.record == retry.record
    good = DiaryConfirmation(opening_status="confirmed", closing_status="confirmed")
    one = confirm_diary("demo-cafe", NOW.date(), good, now=NOW, settings=audit_settings)
    changed = DiaryConfirmation(
        opening_status="exception", closing_status="confirmed", note="Later"
    )
    two = confirm_diary("demo-cafe", NOW.date(), changed, now=NOW, settings=audit_settings)
    assert one.created and not two.created and one.record == two.record
    assert audit.get_diary_record("demo-cafe", diary_id(NOW.date()), audit_settings) == first.record


def test_mixed_history_paginates_and_recall_reader_survives(audit_settings: Settings) -> None:
    for number in range(4):
        audit.append_audit_entry(entry(number), audit_settings)
    audit.append_diary_record(filed_record(), audit_settings)
    assert len(audit.list_history("demo-cafe", audit_settings, page_size=1)) == 5
    assert len(audit.list_audit_entries("demo-cafe", audit_settings, page_size=1)) == 4
    assert audit.get_audit_entry("demo-cafe", entry().entry_id, audit_settings) == entry()


@pytest.mark.parametrize("day_offset,business", [(1, "demo-cafe"), (0, "another-cafe")])
def test_date_and_business_keys_are_independent(
    audit_settings: Settings, day_offset: int, business: str
) -> None:
    first = run_daily_diary("demo-cafe", NOW.date(), now=NOW, settings=audit_settings)
    later = NOW + timedelta(days=day_offset)
    second = run_daily_diary(business, later.date(), now=later, settings=audit_settings)
    assert first.created and second.created


def test_confirmation_requires_filing_and_valid_time(audit_settings: Settings) -> None:
    answers = DiaryConfirmation(opening_status="confirmed", closing_status="confirmed")
    with pytest.raises(ValueError, match="File the diary"):
        confirm_diary("demo-cafe", NOW.date(), answers, now=NOW, settings=audit_settings)
    audit.append_diary_record(filed_record(), audit_settings)
    with pytest.raises(ValueError, match="precede"):
        confirm_diary(
            "demo-cafe",
            NOW.date(),
            answers,
            now=NOW - timedelta(seconds=1),
            settings=audit_settings,
        )
    with pytest.raises(ValueError, match="File the diary"):
        confirm_diary("other", NOW.date(), answers, now=NOW, settings=audit_settings)


def test_unknown_history_is_never_silently_omitted(audit_settings: Settings) -> None:
    table = boto3.resource("dynamodb", region_name=audit_settings.aws_region).Table(
        audit_settings.dynamodb_table_audit
    )
    table.put_item(Item={"business_id": "demo-cafe", "entry_id": "unknown", "event": "alien"})
    with pytest.raises(audit.AuditPersistenceError):
        audit.list_history("demo-cafe", audit_settings)
    with pytest.raises(audit.AuditPersistenceError):
        audit.list_audit_entries("demo-cafe", audit_settings)


def test_uncertain_append_never_acknowledges_success(audit_settings: Settings) -> None:
    with patch("src.tools.audit._table") as table:
        table.return_value.put_item.side_effect = EndpointConnectionError(
            endpoint_url="https://invalid.test"
        )
        with pytest.raises(audit.AuditPersistenceError, match="unknown"):
            audit.append_diary_record(filed_record(), audit_settings)


def test_preparation_error_is_recorded_without_a_filing(audit_settings: Settings) -> None:
    with patch("src.runtime.daily_diary.build_diary_entry", side_effect=ValueError("bad facts")):
        with pytest.raises(ValueError):
            run_daily_diary("demo-cafe", NOW.date(), now=NOW, settings=audit_settings)
    rows = audit.list_history("demo-cafe", audit_settings)
    assert len(rows) == 1 and isinstance(rows[0], DiaryRecord)
    assert rows[0].event is DiaryEvent.ERROR and rows[0].error_type == "ValueError"
