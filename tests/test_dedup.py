"""Unit tests for pure alert-version deduplication."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from src.domain.dedup import filter_unseen_alerts
from src.domain.models import Alert, AlertType


def _alert(alert_id: str, modified: datetime) -> Alert:
    """Build a small valid alert for pure deduplication tests."""
    return Alert(
        id=alert_id,
        id_uri=f"https://example.test/{alert_id}",
        type=AlertType.AA,
        title=f"Alert {alert_id}",
        description=None,
        created=date(2026, 9, 9),
        modified=modified,
        status="Published",
        alert_url=None,
        allergens=[],
        products=[],
    )


def test_empty_alert_list_returns_an_empty_list() -> None:
    """No input alerts means no output alerts."""
    assert filter_unseen_alerts([], set()) == []


def test_unseen_alerts_are_kept_in_their_original_order() -> None:
    """The FSA's newest-first order remains unchanged."""
    first = _alert("FSA-AA-2-2026", datetime(2026, 9, 9, 12, tzinfo=UTC))
    second = _alert("FSA-AA-1-2026", datetime(2026, 9, 9, 11, tzinfo=UTC))

    assert filter_unseen_alerts([first, second], set()) == [first, second]


def test_exactly_seen_version_is_removed() -> None:
    """The same alert ID and modified time must not be processed twice."""
    alert = _alert("FSA-AA-1-2026", datetime(2026, 9, 9, 12, tzinfo=UTC))

    result = filter_unseen_alerts(
        [alert],
        {(alert.id, alert.modified)},
    )

    assert result == []


def test_newer_version_of_the_same_alert_id_is_returned() -> None:
    """A changed FSA alert must resurface for downstream processing."""
    original_time = datetime(2026, 9, 9, 12, tzinfo=UTC)
    updated_time = original_time + timedelta(hours=1)

    updated_alert = _alert("FSA-AA-1-2026", updated_time)

    result = filter_unseen_alerts(
        [updated_alert],
        {("FSA-AA-1-2026", original_time)},
    )

    assert result == [updated_alert]
