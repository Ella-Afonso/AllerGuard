"""Conditional escalation queue writes, tenant isolation, and first-row wins."""

from __future__ import annotations

import inspect
from datetime import timedelta

import boto3
import pytest

from src.config import Settings
from src.domain.models import (
    ActionPack,
    ConfidenceTier,
    DraftSource,
    Escalation,
    EscalationStatus,
)
from src.tools import escalation_queue
from tests.audit_support import NOW


def _pack(*, pull: str = "Remove the walnut brownie from sale.") -> ActionPack:
    return ActionPack(
        pull=pull,
        staff_note="Do not serve the walnut brownie until it has been checked.",
        customer_notice="Draft only. This customer notice has not been sent.",
        substitution="No substitution suggested.",
    )


def row(number: int = 1, *, business_id: str = "demo-cafe") -> Escalation:
    identity = f"{number:064x}"
    return Escalation(
        escalation_id=identity,
        business_id=business_id,
        assessment_id=identity,
        alert_id=f"synthetic-{number}",
        alert_modified=NOW,
        alert_title="Fictional recall",
        source_url="https://example.org/recall",
        status=EscalationStatus.PENDING,
        tier=ConfidenceTier.LIKELY,
        floor_tier=ConfidenceTier.POSSIBLE,
        reason="The fictional menu lists a matching product.",
        action_pack=_pack(),
        draft_source=DraftSource.MODEL,
        policy_version="matcher-gate-v1",
        draft_policy_version="action-draft-v1",
        drafter_model_id="injected-proposal",
        queued_at=NOW,
    )


def test_ensure_table_creates_escalation_table(audit_settings: Settings) -> None:
    client = boto3.client("dynamodb", region_name=audit_settings.aws_region)
    assert audit_settings.dynamodb_table_escalations in client.list_tables()["TableNames"]


def test_ensure_table_is_idempotent(audit_settings: Settings) -> None:
    escalation_queue.ensure_escalation_table(audit_settings)
    escalation_queue.ensure_escalation_table(audit_settings)
    client = boto3.client("dynamodb", region_name=audit_settings.aws_region)
    names = client.list_tables()["TableNames"]
    assert names.count(audit_settings.dynamodb_table_escalations) == 1


def test_queue_and_get_round_trip(audit_settings: Settings) -> None:
    original = row()
    stored = escalation_queue.queue_escalation(original, audit_settings)
    assert stored.created is True
    read_back = escalation_queue.get_escalation(
        original.business_id, original.escalation_id, audit_settings
    )
    assert read_back == original


def test_exact_duplicate_preserves_first_stored_row(audit_settings: Settings) -> None:
    original = row()
    first = escalation_queue.queue_escalation(original, audit_settings)
    later = original.model_copy(
        update={
            "queued_at": NOW + timedelta(hours=1),
            "draft_source": DraftSource.FALLBACK,
            "drafter_model_id": "fallback",
            "action_pack": _pack(pull="A later writer must not replace this pack."),
        }
    )
    retry = escalation_queue.queue_escalation(later, audit_settings)
    assert first.created is True
    assert retry.created is False
    assert retry.escalation == original
    assert retry.escalation.action_pack == original.action_pack
    assert retry.escalation.draft_source is DraftSource.MODEL
    assert retry.escalation.drafter_model_id == "injected-proposal"
    assert retry.escalation.queued_at == NOW
    assert (
        escalation_queue.get_escalation(
            original.business_id, original.escalation_id, audit_settings
        )
        == original
    )


def test_incompatible_identity_fields_raise_on_duplicate(audit_settings: Settings) -> None:
    original = row()
    escalation_queue.queue_escalation(original, audit_settings)
    conflicting = original.model_copy(update={"alert_id": "different-synthetic-alert"})
    with pytest.raises(
        escalation_queue.EscalationPersistenceError, match="incompatible identity fields"
    ):
        escalation_queue.queue_escalation(conflicting, audit_settings)
    assert (
        escalation_queue.get_escalation(
            original.business_id, original.escalation_id, audit_settings
        )
        == original
    )


def test_two_businesses_are_isolated(audit_settings: Settings) -> None:
    for name in ("demo-cafe", "fictional-other"):
        escalation_queue.queue_escalation(row(business_id=name), audit_settings)
    assert escalation_queue.list_pending("demo-cafe", audit_settings) == [row()]
    assert escalation_queue.list_pending("absent", audit_settings) == []


def test_list_pending_returns_only_pending_rows(audit_settings: Settings) -> None:
    first = row(1)
    second = row(2).model_copy(update={"queued_at": NOW + timedelta(minutes=1)})
    escalation_queue.queue_escalation(first, audit_settings)
    escalation_queue.queue_escalation(second, audit_settings)
    listed = escalation_queue.list_pending("demo-cafe", audit_settings)
    assert listed == [first, second]
    assert all(item.status is EscalationStatus.PENDING for item in listed)
    source = inspect.getsource(escalation_queue.list_pending)
    assert "EscalationStatus.PENDING" in source


def test_queries_read_all_pages_and_sort_by_queued_at(audit_settings: Settings) -> None:
    originals = [
        row(n).model_copy(update={"queued_at": NOW + timedelta(minutes=6 - n)}) for n in range(1, 6)
    ]
    for original in originals:
        escalation_queue.queue_escalation(original, audit_settings)
    actual = escalation_queue.list_pending("demo-cafe", audit_settings, page_size=2)
    assert actual == list(reversed(originals))


def test_conditional_put_handles_racing_writer(
    audit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = escalation_queue._table(audit_settings)
    original = row()

    class RacingTable:
        def put_item(self, **kwargs: object) -> None:
            table.put_item(Item=original.model_dump(mode="json"))
            table.put_item(**kwargs)

        def get_item(self, **kwargs: object) -> object:
            return table.get_item(**kwargs)

    monkeypatch.setattr(escalation_queue, "_table", lambda _: RacingTable())
    stored = escalation_queue.queue_escalation(original, audit_settings)
    assert stored.created is False
    assert stored.escalation == original
    assert (
        escalation_queue.get_escalation(
            original.business_id, original.escalation_id, audit_settings
        )
        == original
    )


def test_queue_tool_source_does_not_call_update_or_delete() -> None:
    source = inspect.getsource(escalation_queue)
    assert "update_item" not in source.casefold()
    assert "delete_item" not in source.casefold()
    assert not hasattr(escalation_queue, "update_escalation")
    assert not hasattr(escalation_queue, "delete_escalation")
    assert not hasattr(escalation_queue, "set_escalation_status")
