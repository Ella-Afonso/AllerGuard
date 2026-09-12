"""Real Moto pipeline proofs at the batch boundary; no paid model or delivery."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts.demo_gate_audit import SCENARIOS, _failed_assessor, _offline_assessor, _offline_drafter
from scripts.demo_human_loop import _simulated_notifier
from src.config import Settings
from src.domain.cycle import CycleReport, CycleStatus
from src.domain.demo_cafe import build_demo_profile
from src.domain.models import (
    Escalation,
    NotificationMode,
    NotificationOutcome,
    NotificationProvider,
    NotificationReceipt,
)
from src.runtime import cycle
from src.tools import alert_ledger, audit, escalation_queue


@pytest.fixture
def cycle_settings(audit_settings: Settings, tmp_path: Path) -> Settings:
    items: list[object] = []
    for name in SCENARIOS["full"]:
        items.extend(
            json.loads((Path("fixtures") / f"{name}.json").read_text(encoding="utf-8"))["items"]
        )
    replay = tmp_path / "batch.json"
    replay.write_text(json.dumps({"items": items}), encoding="utf-8")
    settings = audit_settings.model_copy(
        update={
            "fsa_fixtures_path": replay,
            "notification_mode": "ses",
            "ses_from_email": "owner@example.test",
            "owner_email": "owner@example.test",
        }
    )
    alert_ledger.ensure_alerts_seen_table(settings)
    return settings


def run(settings: Settings, calls: list[str]) -> CycleReport:
    return cycle.run_monitoring_cycle(
        build_demo_profile(),
        settings=settings,
        assessor=_offline_assessor,
        drafter=_offline_drafter,
        notifier=_simulated_notifier(calls),
    )


def snapshot(settings: Settings) -> tuple[list[str], list[str]]:
    return (
        [row.model_dump_json() for row in audit.list_audit_entries("demo-cafe", settings)],
        [row.model_dump_json() for row in escalation_queue.list_pending("demo-cafe", settings)],
    )


def test_five_then_zero_uses_ledger_and_has_no_more_effects(cycle_settings: Settings) -> None:
    calls: list[str] = []
    first = run(cycle_settings, calls)
    assert first.status is CycleStatus.COMMITTED
    assert (first.retrieved, first.silent, first.escalated, first.blocked) == (5, 2, 3, 0)
    assert first.watermark_after == max(row.modified for row in first.alerts)
    stored = snapshot(cycle_settings)
    assert len(stored[0]) == 11 and len(stored[1]) == 3 and len(calls) == 3
    with (
        patch.object(cycle, "process_alert", side_effect=AssertionError("unexpected processing")),
        patch.object(
            alert_ledger, "commit_processed_batch", side_effect=AssertionError("unexpected commit")
        ),
    ):
        second = run(cycle_settings, calls)
    assert second.status is CycleStatus.EMPTY and second.retrieved == 0
    assert second.watermark_after == first.watermark_after
    assert snapshot(cycle_settings) == stored and len(calls) == 3


def test_empty_feed_does_not_write(cycle_settings: Settings) -> None:
    cycle_settings.fsa_fixtures_path.write_text('{"items": []}', encoding="utf-8")
    result = run(cycle_settings, [])
    assert result.status is CycleStatus.EMPTY
    assert result.watermark_after is None
    assert alert_ledger.list_seen_versions(cycle_settings) == []


def test_handled_matcher_failure_with_fallback_can_commit(cycle_settings: Settings) -> None:
    result = cycle.run_monitoring_cycle(
        build_demo_profile(),
        settings=cycle_settings,
        assessor=_failed_assessor,
        drafter=_offline_drafter,
        notifier=_simulated_notifier([]),
    )
    assert result.status is CycleStatus.COMMITTED
    assert result.escalated == result.handled_errors == 5
    assert all(
        row.draft_source.value == "fallback"
        for row in escalation_queue.list_pending("demo-cafe", cycle_settings)
    )


def test_interrupted_alert_continues_batch_and_retry_reuses_persisted_rows(
    cycle_settings: Settings,
) -> None:
    calls: list[str] = []
    original = cycle.process_alert
    attempts = 0

    def interrupted(*args: object, **kwargs: object) -> object:
        nonlocal attempts
        attempts += 1
        result = original(*args, **kwargs)
        if attempts == 1:
            raise RuntimeError("synthetic crash after persistence")
        return result

    with patch.object(cycle, "process_alert", side_effect=interrupted):
        first = run(cycle_settings, calls)
    assert first.status is CycleStatus.BLOCKED and first.blocked == 1
    assert attempts == 5
    assert alert_ledger.read_alert_watermark(cycle_settings) is None
    assert len(alert_ledger.load_new_alerts(cycle_settings)) == 5
    original_rows = snapshot(cycle_settings)
    second = run(cycle_settings, calls)
    assert second.status is CycleStatus.COMMITTED
    assert snapshot(cycle_settings) == original_rows and len(calls) == 3


def test_crash_immediately_before_commit_preserves_replay(cycle_settings: Settings) -> None:
    calls: list[str] = []
    with patch.object(alert_ledger, "commit_processed_batch", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            run(cycle_settings, calls)
    original_rows = snapshot(cycle_settings)
    assert alert_ledger.read_alert_watermark(cycle_settings) is None
    assert alert_ledger.list_seen_versions(cycle_settings) == []
    assert len(alert_ledger.load_new_alerts(cycle_settings)) == 5
    assert run(cycle_settings, calls).status is CycleStatus.COMMITTED
    assert snapshot(cycle_settings) == original_rows and len(calls) == 3


@pytest.mark.parametrize("outcome", [NotificationOutcome.FAILED, NotificationOutcome.UNKNOWN])
def test_unresolved_notification_blocks_commit(
    cycle_settings: Settings, outcome: NotificationOutcome
) -> None:
    calls: list[str] = []

    def sender(row: Escalation, settings: Settings, timestamp: datetime) -> NotificationReceipt:
        calls.append(row.escalation_id)
        return NotificationReceipt(
            business_id=row.business_id,
            escalation_id=row.escalation_id,
            outcome=outcome,
            mode=NotificationMode.SIMULATED,
            provider=NotificationProvider.STUB,
            attempted_at=timestamp,
            failure_type="SyntheticFailure",
        )

    for _ in range(2):
        result = cycle.run_monitoring_cycle(
            build_demo_profile(),
            settings=cycle_settings,
            assessor=_offline_assessor,
            drafter=_offline_drafter,
            notifier=sender,
        )
        assert result.status is CycleStatus.BLOCKED and result.blocked == 3
        assert alert_ledger.read_alert_watermark(cycle_settings) is None
    assert len(calls) == (3 if outcome is NotificationOutcome.UNKNOWN else 6)


def test_disabled_notification_is_explicit_no_delivery_mode(cycle_settings: Settings) -> None:
    calls: list[str] = []
    result = run(cycle_settings.model_copy(update={"notification_mode": "disabled"}), calls)
    assert result.status is CycleStatus.COMMITTED and not calls
    assert len(snapshot(cycle_settings)[0]) == 8


def test_storage_outage_blocks_batch(cycle_settings: Settings) -> None:
    with patch("src.runtime.process_alert.queue_escalation", side_effect=RuntimeError("outage")):
        result = run(cycle_settings, [])
    assert result.status is CycleStatus.BLOCKED and result.blocked == 3
    assert alert_ledger.read_alert_watermark(cycle_settings) is None


def test_commit_exception_never_claims_success(cycle_settings: Settings) -> None:
    with patch.object(
        alert_ledger, "commit_processed_batch", side_effect=RuntimeError("commit outage")
    ):
        result = run(cycle_settings, [])
    assert result.status is CycleStatus.COMMIT_UNKNOWN
    assert result.watermark_after is None


def test_updated_version_is_retrieved_and_processed(cycle_settings: Settings) -> None:
    first = run(cycle_settings, [])
    payload = json.loads(cycle_settings.fsa_fixtures_path.read_text(encoding="utf-8"))
    payload["items"][0]["modified"] = (first.watermark_after + timedelta(days=1)).isoformat()
    cycle_settings.fsa_fixtures_path.write_text(json.dumps(payload), encoding="utf-8")
    second = run(cycle_settings, [])
    assert second.status is CycleStatus.COMMITTED and second.retrieved == 1


def test_source_failure_is_blocked_not_empty(cycle_settings: Settings) -> None:
    with patch.object(alert_ledger, "load_new_alerts", side_effect=RuntimeError("source")):
        result = run(cycle_settings, [])
    assert result.status is CycleStatus.BLOCKED and result.error_type == "RuntimeError"


def test_partial_ledger_write_is_reported_uncertain(cycle_settings: Settings) -> None:
    table = alert_ledger._table(cycle_settings)
    proxy = Mock(wraps=table)

    def put(*, Item: dict[str, str]) -> object:
        if Item["alert_id"] == "_watermark":
            raise RuntimeError("watermark unavailable")
        return table.put_item(Item=Item)

    proxy.put_item.side_effect = put
    with patch.object(alert_ledger, "_table", return_value=proxy):
        result = run(cycle_settings, [])
    assert result.status is CycleStatus.COMMIT_UNKNOWN
    assert len(alert_ledger.list_seen_versions(cycle_settings)) == 5
    assert alert_ledger.read_alert_watermark(cycle_settings) is None
