"""Tests for the DynamoDB alert-version ledger."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import boto3
import pytest
from moto import mock_aws

from src.config import Settings
from src.domain.models import Alert
from src.tools.alert_ledger import (
    commit_processed_batch,
    ensure_alerts_seen_table,
    get_new_alerts,
    list_seen_versions,
    load_new_alerts,
    read_alert_watermark,
)
from src.tools.fsa_api import load_alerts


@pytest.fixture
def mocked_aws() -> Iterator[None]:
    """Run DynamoDB tests against Moto instead of a real AWS account."""
    with mock_aws():
        yield


@pytest.fixture
def ledger_settings(
    monkeypatch: pytest.MonkeyPatch,
    mocked_aws: None,
) -> Settings:
    """Configure deterministic replay and mocked DynamoDB settings."""
    monkeypatch.setenv("AWS_REGION", "eu-west-2")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    monkeypatch.setenv("ALLERGUARD_FSA_MODE", "replay")
    monkeypatch.setenv(
        "ALLERGUARD_FSA_FIXTURES_PATH",
        str(Path("fixtures/alerts_recent.json")),
    )
    monkeypatch.setenv(
        "ALLERGUARD_DYNAMODB_TABLE_ALERTS_SEEN",
        "allerguard-alerts-seen-test",
    )

    settings = Settings.from_environment()
    ensure_alerts_seen_table(settings)

    return settings


def _latest_watermark(alerts: list[Alert]) -> str:
    """Return the latest alert timestamp as a UTC Z-formatted watermark."""
    latest_modified = max(alert.modified for alert in alerts)

    return latest_modified.astimezone(UTC).isoformat().replace("+00:00", "Z")


def test_explicit_settings_do_not_read_environment(ledger_settings: Settings) -> None:
    expected = load_alerts(ledger_settings)
    with patch.object(Settings, "from_environment", side_effect=AssertionError("environment")):
        assert load_new_alerts(ledger_settings) == expected


def test_watermark_compares_fractional_seconds_as_times(ledger_settings: Settings) -> None:
    alert = load_alerts(ledger_settings)[0].model_copy(
        update={"modified": datetime(2026, 9, 12, tzinfo=UTC)}
    )
    commit_processed_batch("2026-09-12T00:00:00.100000Z", [alert], ledger_settings)
    assert read_alert_watermark(ledger_settings) == "2026-09-12T00:00:00.100000Z"
    later = alert.model_copy(
        update={"modified": datetime(2026, 9, 12, microsecond=200000, tzinfo=UTC)}
    )
    with pytest.raises(ValueError):
        commit_processed_batch("2026-09-12T00:00:00Z", [later], ledger_settings)


def test_serial_commit_does_not_move_watermark_backward(ledger_settings: Settings) -> None:
    alerts = load_alerts(ledger_settings)
    commit_processed_batch("2026-12-01T00:00:00Z", alerts, ledger_settings)
    commit_processed_batch(_latest_watermark(alerts), alerts, ledger_settings)
    assert read_alert_watermark(ledger_settings) == "2026-12-01T00:00:00Z"


def test_partial_commit_is_not_an_atomic_rollback(ledger_settings: Settings) -> None:
    from src.tools import alert_ledger

    alerts = load_alerts(ledger_settings)
    table = alert_ledger._table(ledger_settings)
    proxy = Mock(wraps=table)

    def put(*, Item: dict[str, str]) -> object:
        if Item["alert_id"] == "_watermark":
            raise RuntimeError("synthetic watermark outage")
        return table.put_item(Item=Item)

    proxy.put_item.side_effect = put
    with patch.object(alert_ledger, "_table", return_value=proxy), pytest.raises(RuntimeError):
        commit_processed_batch(_latest_watermark(alerts), alerts, ledger_settings)
    assert read_alert_watermark(ledger_settings) is None
    assert len(list_seen_versions(ledger_settings)) == len(alerts)
    # All processed versions were saved. Retry retrieval is empty; no false claim
    # that the entire batch reappears after a partially completed ledger write.
    assert load_new_alerts(ledger_settings) == []


def test_ledger_table_creation_is_idempotent(ledger_settings: Settings) -> None:
    """Creating the same ledger table twice succeeds safely."""
    ensure_alerts_seen_table(ledger_settings)

    table = boto3.client(
        "dynamodb",
        region_name=ledger_settings.aws_region,
    ).describe_table(
        TableName=ledger_settings.dynamodb_table_alerts_seen,
    )

    assert table["Table"]["TableStatus"] == "ACTIVE"


def test_new_ledger_has_no_watermark_or_seen_versions(
    ledger_settings: Settings,
) -> None:
    """A fresh ledger starts empty."""
    assert read_alert_watermark(ledger_settings) is None
    assert list_seen_versions(ledger_settings) == []


def test_commit_records_versions_and_hides_the_watermark_item(
    ledger_settings: Settings,
) -> None:
    """A successful batch writes alert versions before its watermark."""
    alerts = load_alerts(ledger_settings)[:2]
    watermark = _latest_watermark(alerts)

    commit_processed_batch(
        watermark,
        alerts,
        ledger_settings,
    )

    seen_versions = list_seen_versions(ledger_settings)

    assert read_alert_watermark(ledger_settings) == watermark
    assert {(seen.alert_id, seen.modified) for seen in seen_versions} == {
        (alert.id, alert.modified) for alert in alerts
    }


def test_repeating_the_same_commit_is_idempotent(
    ledger_settings: Settings,
) -> None:
    """Writing the same processed batch twice does not create duplicates."""
    alerts = load_alerts(ledger_settings)[:2]
    watermark = _latest_watermark(alerts)

    commit_processed_batch(watermark, alerts, ledger_settings)
    commit_processed_batch(watermark, alerts, ledger_settings)

    assert len(list_seen_versions(ledger_settings)) == len(alerts)


def test_uncommitted_batch_reappears_after_a_simulated_crash(
    ledger_settings: Settings,
) -> None:
    """No commit means the next run returns the same replay alerts again."""
    first_run = get_new_alerts()
    second_run = get_new_alerts()

    assert first_run == second_run
    assert read_alert_watermark(ledger_settings) is None


def test_committed_batch_is_not_returned_again(
    ledger_settings: Settings,
) -> None:
    """After a successful commit, replayed alert versions are filtered out."""
    alerts = get_new_alerts()
    watermark = _latest_watermark(alerts)

    commit_processed_batch(watermark, alerts, ledger_settings)

    assert get_new_alerts() == []
