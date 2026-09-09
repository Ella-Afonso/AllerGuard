"""Pure helpers for exact FSA alert-version deduplication."""

from __future__ import annotations

from datetime import datetime

from src.domain.models import Alert


def filter_unseen_alerts(
    alerts: list[Alert],
    seen_versions: set[tuple[str, datetime]],
) -> list[Alert]:
    """Return only alert versions not already present in the ledger.

    The incoming FSA order is preserved. An alert with the same ID but a newer
    modified timestamp is a new version and must be returned for reprocessing.
    """
    return [alert for alert in alerts if (alert.id, alert.modified) not in seen_versions]
