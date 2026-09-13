"""Scheduled entry reuses real offline persistence and reports failures honestly."""

from unittest.mock import patch

import pytest

from src.runtime.scheduled_cycle import handler
from src.tools.demo_sessions import DemoSessions


def test_scheduled_persistence_and_empty_retry() -> None:
    manager = DemoSessions()
    manager.start()
    try:
        _, session = manager.create()
        settings = session.settings.model_copy(
            update={
                "notification_mode": "disabled",
                "cycle_proposal_mode": "injected",
            }
        )
        with patch("src.runtime.scheduled_cycle.Settings.from_environment", return_value=settings):
            first = handler({"business_id": "untrusted"}, None)
            second = handler({}, None)
        assert first["cycle"]["status"] == "committed"
        assert first["cycle"]["retrieved"] == 5
        assert first["cycle"]["silent"] == 2
        assert first["cycle"]["escalated"] == 3
        assert second["cycle"]["status"] == "empty"
    finally:
        manager.close()


def test_scheduled_failure_raises() -> None:
    manager = DemoSessions()
    manager.start()
    try:
        _, session = manager.create()
        settings = session.settings.model_copy(update={"notification_mode": "disabled"})
        with (
            patch("src.runtime.scheduled_cycle.Settings.from_environment", return_value=settings),
            patch("src.runtime.cycle.alert_ledger.load_new_alerts", side_effect=RuntimeError),
            pytest.raises(RuntimeError, match="blocked"),
        ):
            handler({}, None)
    finally:
        manager.close()
