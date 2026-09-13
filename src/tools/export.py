"""Complete read-only CSV and HTML exports from one retrieved audit collection."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.config import Settings
from src.domain.diary import DiaryEvent, DiaryRecord, DiaryView, build_diary_view, business_date
from src.domain.models import AuditEntry
from src.tools.audit import HistoryRecord, list_history
from src.tools.audit_report import write_audit_report


class ExportResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    csv_path: Path
    html_path: Path
    event_count: int


def spreadsheet_text(value: str) -> str:
    """Keep human text literal in spreadsheets; payload JSON retains the original."""
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def diary_views(rows: list[HistoryRecord], *, as_of: datetime) -> list[DiaryView]:
    recalls = [row for row in rows if isinstance(row, AuditEntry)]
    diaries = [row for row in rows if isinstance(row, DiaryRecord)]
    filed = {
        (row.business_id, row.entry_date): row for row in diaries if row.event is DiaryEvent.FILED
    }
    confirmations = {
        (row.business_id, row.entry_date): row
        for row in diaries
        if row.event is DiaryEvent.CONFIRMED
    }
    if confirmations.keys() - filed.keys():
        raise ValueError("History contains an orphan diary confirmation.")
    return [
        build_diary_view(row, confirmations.get(key), recalls, as_of=as_of)
        for key, row in sorted(filed.items())
    ]


def write_csv(rows: list[HistoryRecord], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "event_id",
        "event_type",
        "timestamp",
        "business_id",
        "diary_date",
        "assessment_id",
        "alert_id",
        "alert_title",
        "owner_choice",
        "opening_status",
        "closing_status",
        "notes",
        "payload_json",
    )
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows, key=lambda item: (item.timestamp, item.entry_id)):
            values = {field: "" for field in fields}
            values.update(
                event_id=row.entry_id,
                event_type=row.event.value,
                timestamp=row.timestamp.isoformat(),
                business_id=row.business_id,
                payload_json=row.model_dump_json(),
            )
            if isinstance(row, AuditEntry):
                values.update(
                    assessment_id=row.assessment_id,
                    alert_id=row.alert_id,
                    alert_title=row.alert_title,
                )
                if row.owner_decision is not None:
                    values["owner_choice"] = row.owner_decision.decision.value
            else:
                values["diary_date"] = row.entry_date.isoformat()
                if row.diary is not None:
                    values.update(
                        opening_status=row.diary.opening_status.value,
                        closing_status=row.diary.closing_status.value,
                        notes=row.diary.notes,
                    )
                if row.confirmation is not None:
                    values.update(
                        opening_status=row.confirmation.opening_status.value,
                        closing_status=row.confirmation.closing_status.value,
                        notes=row.confirmation.note,
                    )
            writer.writerow({key: spreadsheet_text(value) for key, value in values.items()})
    return output.resolve()


def export_evidence(
    business_id: str,
    *,
    csv_path: Path,
    html_path: Path,
    settings: Settings,
    as_of: datetime,
    storage_label: str,
) -> ExportResult:
    """Read once, validate completely, then render both formats. Not an atomic DB snapshot."""
    if csv_path.resolve() == html_path.resolve():
        raise ValueError("CSV and HTML require different output paths.")
    business_date(as_of)
    rows = list_history(business_id, settings)
    if any(row.timestamp > as_of for row in rows):
        raise ValueError("Export time precedes stored evidence; choose a later as-of time.")
    views = diary_views(rows, as_of=as_of)
    recalls = [row for row in rows if isinstance(row, AuditEntry)]
    diaries = [row for row in rows if isinstance(row, DiaryRecord)]
    html = write_audit_report(
        recalls, html_path, storage_label=storage_label, diary_views=views, diary_records=diaries
    )
    csv_output = write_csv(rows, csv_path)
    return ExportResult(csv_path=csv_output, html_path=html, event_count=len(rows))
