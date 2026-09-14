"""An explicit initial lookback never masquerades as committed processing."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.tools.alert_ledger import load_new_alerts


def test_initial_since_requires_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLERGUARD_FSA_INITIAL_SINCE", "2026-09-01T00:00:00")
    with pytest.raises(ValidationError):
        Settings.from_environment()


def test_environment_reads_initial_since(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLERGUARD_FSA_INITIAL_SINCE", "2026-09-01T01:00:00+01:00")
    assert Settings.from_environment().fsa_initial_since == datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("mode", "watermark", "expected"),
    [
        ("live", None, "2026-09-01T00:00:00Z"),
        ("live", "2026-09-03T00:00:00Z", "2026-09-03T00:00:00Z"),
        ("replay", None, None),
    ],
)
def test_lookback_is_only_used_for_first_live_poll(
    mode: str, watermark: str | None, expected: str | None
) -> None:
    settings = Settings.model_validate(
        {
            "aws_region": "eu-west-2",
            "bedrock_model_id": "offline",
            "fsa_mode": mode,
            "fsa_initial_since": "2026-09-01T01:00:00+01:00",
        }
    )
    with (
        patch("src.tools.alert_ledger.read_alert_watermark", return_value=watermark),
        patch("src.tools.alert_ledger.list_seen_versions", return_value=[]),
        patch("src.tools.alert_ledger.load_alerts", return_value=[]) as loader,
        patch("src.tools.alert_ledger.commit_processed_batch") as commit,
    ):
        assert load_new_alerts(settings) == []
        loader.assert_called_once_with(settings, since=expected)
        commit.assert_not_called()


def test_unconfigured_live_bootstrap_still_fails_before_network() -> None:
    settings = Settings(aws_region="eu-west-2", bedrock_model_id="offline", fsa_mode="live")
    with patch("src.tools.alert_ledger.read_alert_watermark", return_value=None):
        with pytest.raises(ValueError, match="requires since"):
            load_new_alerts(settings)
