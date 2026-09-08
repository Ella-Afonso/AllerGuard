"""Tests for the local current-time tool."""

from __future__ import annotations

from datetime import UTC, datetime

from src.tools.current_time import get_current_utc_time


def test_get_current_utc_time_returns_utc_iso_timestamp() -> None:
    """The tool returns a parseable timestamp in UTC."""
    timestamp = get_current_utc_time()

    parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

    assert parsed_timestamp.tzinfo == UTC
    assert timestamp.endswith("Z")
