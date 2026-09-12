"""Cycle reports cannot miscount handled errors or certify partial batches."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.domain.cycle import AlertOutcome, CycleAlertResult, CycleReport, CycleStatus

NOW = datetime(2026, 9, 12, tzinfo=UTC)


def report(**changes: object) -> CycleReport:
    values: dict[str, object] = {
        "cycle_id": "synthetic-cycle",
        "business_id": "demo-cafe",
        "started_at": NOW,
        "finished_at": NOW,
        "status": CycleStatus.EMPTY,
    }
    values.update(changes)
    return CycleReport.model_validate(values)


def test_handled_error_is_counted_once_and_as_escalated() -> None:
    row = CycleAlertResult(
        alert_id="public-alert",
        modified=NOW,
        outcome=AlertOutcome.HANDLED_ERROR,
        assessment_id="synthetic",
        error_type="MatcherModelError",
    )
    result = report(status=CycleStatus.COMMITTED, alerts=(row,), watermark_after=NOW)
    assert result.retrieved == result.escalated == result.handled_errors == 1
    assert result.silent == result.blocked == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"started_at": NOW.replace(tzinfo=None)},
        {"finished_at": NOW - timedelta(seconds=1)},
        {"status": CycleStatus.COMMITTED},
        {"status": CycleStatus.BLOCKED},
        {"status": CycleStatus.COMMIT_UNKNOWN},
        {"watermark_after": NOW},
        {"retrieved": -1},
    ],
)
def test_contradictory_report_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        report(**changes)


def test_blocked_alert_cannot_be_declared_committed() -> None:
    row = CycleAlertResult(
        alert_id="public-alert",
        modified=NOW,
        outcome=AlertOutcome.BLOCKED,
        error_type="AuditPersistenceError",
    )
    with pytest.raises(ValidationError):
        report(status=CycleStatus.COMMITTED, alerts=(row,), watermark_after=NOW)


def test_duplicate_versions_are_rejected() -> None:
    row = CycleAlertResult(
        alert_id="public-alert",
        modified=NOW,
        outcome=AlertOutcome.SILENT,
        assessment_id="synthetic",
    )
    with pytest.raises(ValidationError):
        report(status=CycleStatus.COMMITTED, alerts=(row, row), watermark_after=NOW)
