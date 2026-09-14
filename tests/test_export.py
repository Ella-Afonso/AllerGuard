"""Both evidence formats are complete and read-only, including hostile note text."""

import csv
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import boto3
import pytest

from src.config import Settings
from src.domain.diary import DiaryConfirmation
from src.runtime.daily_diary import run_daily_diary
from src.tools import audit
from src.tools.diary import confirm_diary
from src.tools.export import export_evidence, spreadsheet_text
from tests.audit_support import NOW
from tests.test_diary import decision_entry


def test_complete_export_escaping_and_no_writes(audit_settings: Settings, tmp_path: Path) -> None:
    audit.append_audit_entry(decision_entry(), audit_settings)
    run_daily_diary("demo-cafe", NOW.date(), now=NOW, settings=audit_settings)
    note = '=HYPERLINK("https://invalid.test")\n<script>alert("x")</script>, café'
    confirm_diary(
        "demo-cafe",
        NOW.date(),
        DiaryConfirmation(opening_status="exception", closing_status="confirmed", note=note),
        now=NOW,
        settings=audit_settings,
    )
    before = audit.list_history("demo-cafe", audit_settings)
    result = export_evidence(
        "demo-cafe",
        csv_path=tmp_path / "diary.csv",
        html_path=tmp_path / "diary.html",
        settings=audit_settings,
        as_of=NOW,
        storage_label="Offline simulated",
    )
    assert result.event_count == 3
    with result.csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 3
    confirmation = next(row for row in rows if row["event_label"] == "Diary confirmation recorded")
    assert confirmation["notes"] == "'" + note
    assert "payload_json" not in confirmation
    html = result.html_path.read_text(encoding="utf-8")
    assert "Daily diary" in html and "&lt;script&gt;" in html and "<script>" not in html
    assert "Technical evidence" not in html
    assert "payload_json" not in html
    assert "display_time" in confirmation
    assert "raw_timestamp" not in confirmation
    assert "event_id" not in confirmation
    assert "PUBLIC BROWSER SIMULATION" not in result.csv_path.read_text(encoding="utf-8-sig")
    assert audit.list_history("demo-cafe", audit_settings) == before


def test_later_links_export_without_changing_filed_snapshot(
    audit_settings: Settings, tmp_path: Path
) -> None:
    first = run_daily_diary("demo-cafe", NOW.date(), now=NOW, settings=audit_settings)
    later = NOW + timedelta(minutes=1)
    audit.append_audit_entry(decision_entry(when=later), audit_settings)
    result = export_evidence(
        "demo-cafe",
        csv_path=tmp_path / "a.csv",
        html_path=tmp_path / "a.html",
        settings=audit_settings,
        as_of=later,
        storage_label="Offline",
    )
    assert "linked after filing" in result.html_path.read_text(encoding="utf-8")
    assert (
        audit.get_diary_record("demo-cafe", first.record.entry_id, audit_settings) == first.record
    )


def test_empty_export_and_path_collision(audit_settings: Settings, tmp_path: Path) -> None:
    result = export_evidence(
        "demo-cafe",
        csv_path=tmp_path / "empty.csv",
        html_path=tmp_path / "empty.html",
        settings=audit_settings,
        as_of=NOW,
        storage_label="Offline",
    )
    assert result.event_count == 0
    with result.csv_path.open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.DictReader(stream)) == []
    with pytest.raises(ValueError, match="different"):
        export_evidence(
            "demo-cafe",
            csv_path=tmp_path / "same",
            html_path=tmp_path / "same",
            settings=audit_settings,
            as_of=NOW,
            storage_label="Offline",
        )


@pytest.mark.parametrize("value", ["=1+1", "+cmd", "-cmd", "@sum(A1)", "  =2", "\ttext", "\rtext"])
def test_spreadsheet_text_is_literal(value: str) -> None:
    assert spreadsheet_text(value) == "'" + value


def test_export_reads_history_once(audit_settings: Settings, tmp_path: Path) -> None:
    with patch("src.tools.export.list_history", wraps=audit.list_history) as read:
        export_evidence(
            "demo-cafe",
            csv_path=tmp_path / "one.csv",
            html_path=tmp_path / "one.html",
            settings=audit_settings,
            as_of=NOW,
            storage_label="Offline",
        )
        assert read.call_count == 1


def test_malformed_history_creates_no_partial_export(
    audit_settings: Settings, tmp_path: Path
) -> None:
    table = boto3.resource("dynamodb", region_name=audit_settings.aws_region).Table(
        audit_settings.dynamodb_table_audit
    )
    table.put_item(Item={"business_id": "demo-cafe", "entry_id": "broken", "event": "unknown"})
    with pytest.raises(audit.AuditPersistenceError):
        export_evidence(
            "demo-cafe",
            csv_path=tmp_path / "bad.csv",
            html_path=tmp_path / "bad.html",
            settings=audit_settings,
            as_of=NOW,
            storage_label="Offline",
        )
    assert not list(tmp_path.iterdir())


def test_export_rejects_time_before_evidence(audit_settings: Settings, tmp_path: Path) -> None:
    audit.append_audit_entry(decision_entry(when=NOW + timedelta(minutes=1)), audit_settings)
    with pytest.raises(ValueError, match="precedes"):
        export_evidence(
            "demo-cafe",
            csv_path=tmp_path / "future.csv",
            html_path=tmp_path / "future.html",
            settings=audit_settings,
            as_of=NOW,
            storage_label="Offline",
        )
    assert not list(tmp_path.iterdir())
