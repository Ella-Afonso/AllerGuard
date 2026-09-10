"""Conditional audit writes, tenant isolation, pagination, and immutable history."""

from __future__ import annotations

from datetime import timedelta

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from pydantic import ValidationError

from src.config import Settings
from src.domain.models import AssessmentMode, AuditEntry, AuditEvent, ConfidenceTier, GateDecision
from src.tools import audit
from tests.audit_support import NOW


def entry(number: int = 1, *, business_id: str = "demo-cafe") -> AuditEntry:
    identity = f"{number:064x}"
    return AuditEntry(
        entry_id=f"{identity}#match_decision",
        assessment_id=identity,
        timestamp=NOW,
        business_id=business_id,
        alert_id=f"synthetic-{number}",
        alert_modified=NOW,
        alert_title="Fictional recall",
        source_url="https://example.org/recall",
        event=AuditEvent.MATCH_DECISION,
        tier=ConfidenceTier.NO_MATCH,
        floor_tier=ConfidenceTier.NO_MATCH,
        decision=GateDecision.SILENT,
        reason="No connection in the supplied fictional inventory.",
        policy_version="test-v1",
        model_id="test-model",
        mode=AssessmentMode.INJECTED,
    )


def test_ensure_table_creates_audit_table(audit_settings: Settings) -> None:
    client = boto3.client("dynamodb", region_name=audit_settings.aws_region)
    assert audit_settings.dynamodb_table_audit in client.list_tables()["TableNames"]


def test_append_and_get_round_trip(audit_settings: Settings) -> None:
    original = entry()
    stored = audit.append_audit_entry(original, audit_settings)
    assert stored.created is True
    read_back = audit.get_audit_entry(original.business_id, original.entry_id, audit_settings)
    assert read_back == original


def test_round_trip_and_duplicate_preserve_original_timestamp(audit_settings: Settings) -> None:
    original = entry()
    first = audit.append_audit_entry(original, audit_settings)
    later = original.model_copy(update={"timestamp": NOW + timedelta(hours=1)})
    retry = audit.append_audit_entry(later, audit_settings)
    assert first.created is True
    assert retry.created is False
    assert retry.entry == original
    assert (
        audit.get_audit_entry(original.business_id, original.entry_id, audit_settings) == original
    )
    assert audit.list_audit_entries("demo-cafe", audit_settings) == [original]


def test_changed_proposal_at_same_key_does_not_rewrite_history(audit_settings: Settings) -> None:
    original = entry()
    audit.append_audit_entry(original, audit_settings)
    changed = original.model_copy(
        update={
            "tier": ConfidenceTier.POSSIBLE,
            "decision": GateDecision.ESCALATE,
            "reason": "A competing assessment has different prose.",
        }
    )
    stored = audit.append_audit_entry(changed, audit_settings)
    assert stored.entry == original
    assert stored.created is False
    assert (
        audit.get_audit_entry(original.business_id, original.entry_id, audit_settings) == original
    )


def test_incompatible_identity_fields_raise_on_duplicate(audit_settings: Settings) -> None:
    original = entry()
    audit.append_audit_entry(original, audit_settings)
    conflicting = original.model_copy(update={"alert_id": "different-synthetic-alert"})
    with pytest.raises(audit.AuditPersistenceError, match="incompatible identity fields"):
        audit.append_audit_entry(conflicting, audit_settings)
    assert (
        audit.get_audit_entry(original.business_id, original.entry_id, audit_settings) == original
    )


def test_two_businesses_are_isolated(audit_settings: Settings) -> None:
    for name in ("demo-cafe", "fictional-other"):
        audit.append_audit_entry(entry(business_id=name), audit_settings)
    assert audit.list_audit_entries("demo-cafe", audit_settings) == [entry()]
    assert audit.list_audit_entries("absent", audit_settings) == []


def test_queries_read_all_pages_and_sort_by_timestamp(audit_settings: Settings) -> None:
    originals = [
        entry(n).model_copy(update={"timestamp": NOW + timedelta(minutes=6 - n)})
        for n in range(1, 6)
    ]
    for original in originals:
        audit.append_audit_entry(original, audit_settings)
    actual = audit.list_audit_entries("demo-cafe", audit_settings, page_size=2)
    assert actual == list(reversed(originals))


def test_conditional_put_handles_racing_writer(
    audit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = audit._table(audit_settings)
    original = entry()

    class RacingTable:
        def put_item(self, **kwargs: object) -> None:
            table.put_item(Item=original.model_dump(mode="json"))
            table.put_item(**kwargs)  # Actual DynamoDB condition now fails.

        def get_item(self, **kwargs: object) -> object:
            return table.get_item(**kwargs)

    monkeypatch.setattr(audit, "_table", lambda _: RacingTable())
    assert audit.append_audit_entry(original, audit_settings).created is False


def test_no_update_or_delete_api() -> None:
    assert not hasattr(audit, "update_audit_entry")
    assert not hasattr(audit, "delete_audit_entry")


def test_permission_denial_is_not_treated_as_a_duplicate(
    audit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DeniedTable:
        def put_item(self, **kwargs: object) -> None:
            raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "PutItem")

    monkeypatch.setattr(audit, "_table", lambda _: DeniedTable())
    with pytest.raises(audit.AuditPersistenceError):
        audit.append_audit_entry(entry(), audit_settings)


def test_ensure_table_is_idempotent_and_checks_schema(audit_settings: Settings) -> None:
    audit.ensure_audit_table(audit_settings)
    client = boto3.client("dynamodb", region_name=audit_settings.aws_region)
    client.create_table(
        TableName="incompatible-audit",
        KeySchema=[{"AttributeName": "wrong", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "wrong", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    with pytest.raises(audit.AuditPersistenceError, match="key schema"):
        audit.ensure_audit_table(
            audit_settings.model_copy(
                update={
                    "dynamodb_table_audit": "incompatible-audit",
                }
            )
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"timestamp": NOW.replace(tzinfo=None)},
        {"decision": GateDecision.ESCALATE},
        {"floor_tier": ConfidenceTier.LIKELY},
        {"entry_id": "random-id"},
        {"reason": ""},
        {"event": AuditEvent.MATCH_ERROR},
    ],
)
def test_inconsistent_records_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AuditEntry.model_validate(entry().model_dump() | changes)


def test_audit_model_cannot_be_mutated() -> None:
    original = entry()
    with pytest.raises(ValidationError, match="frozen"):
        original.reason = "Rewrite the history"


def test_lost_write_acknowledgement_is_safe_to_retry(
    audit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = audit._table(audit_settings)
    original = entry()

    class LostAcknowledgement:
        def put_item(self, **kwargs: object) -> None:
            table.put_item(**kwargs)
            raise EndpointConnectionError(endpoint_url="https://dynamodb.example.invalid")

    with monkeypatch.context() as context:
        context.setattr(audit, "_table", lambda _: LostAcknowledgement())
        with pytest.raises(audit.AuditPersistenceError, match="unknown"):
            audit.append_audit_entry(original, audit_settings)
    retry = audit.append_audit_entry(original, audit_settings)
    assert retry.created is False
    assert retry.entry == original
    assert audit.list_audit_entries("demo-cafe", audit_settings) == [original]


def test_invalid_stored_record_is_not_returned_as_a_silent_success(
    audit_settings: Settings,
) -> None:
    original = entry()
    # Simulate corruption outside the application's only conditional-write API.
    raw = original.model_dump(mode="json") | {"tier": "LIKELY", "decision": "silent"}
    audit._table(audit_settings).put_item(Item=raw)
    with pytest.raises(audit.AuditPersistenceError):
        audit.get_audit_entry("demo-cafe", original.entry_id, audit_settings)
    with pytest.raises(audit.AuditPersistenceError):
        audit.list_audit_entries("demo-cafe", audit_settings)
