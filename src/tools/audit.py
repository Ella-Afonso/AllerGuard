"""Append-only DynamoDB audit boundary, called by code, never at a model's discretion."""

from __future__ import annotations

import logging
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import TypeAdapter

from src.config import Settings
from src.domain.diary import DiaryAppendResult, DiaryEvent, DiaryRecord, diary_id
from src.domain.models import AuditAppendResult, AuditEntry, GateDecision

HistoryRecord = AuditEntry | DiaryRecord
HISTORY_ADAPTER: TypeAdapter[HistoryRecord] = TypeAdapter(HistoryRecord)

logger = logging.getLogger(__name__)
AUDIT_KEY_SCHEMA = [
    {"AttributeName": "business_id", "KeyType": "HASH"},
    {"AttributeName": "entry_id", "KeyType": "RANGE"},
]


class AuditPersistenceError(RuntimeError):
    """No recorded outcome can be acknowledged; caller must surface and retry."""

    decision = GateDecision.ESCALATE


def _table(settings: Settings) -> Any:
    """Dynamic boto3 Table proxy; AWS shapes stop at this tool boundary."""
    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(
        settings.dynamodb_table_audit
    )


def ensure_audit_table(settings: Settings | None = None) -> None:
    """Provision the audit table explicitly, including safe concurrent creation.

    Runtime reads/writes never create tables. Setup permissions belong to the
    operator; a runtime identity only needs GetItem, Query, and PutItem.
    """
    resolved = settings or Settings.from_environment()
    client = boto3.client("dynamodb", region_name=resolved.aws_region)
    name = resolved.dynamodb_table_audit
    try:
        client.describe_table(TableName=name)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        try:
            client.create_table(
                TableName=name,
                KeySchema=AUDIT_KEY_SCHEMA,
                AttributeDefinitions=[
                    {"AttributeName": "business_id", "AttributeType": "S"},
                    {"AttributeName": "entry_id", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
                DeletionProtectionEnabled=True,
            )
        except ClientError as create_error:
            if create_error.response["Error"]["Code"] != "ResourceInUseException":
                raise
    client.get_waiter("table_exists").wait(TableName=name)
    table = client.describe_table(TableName=name)["Table"]
    keys = sorted(table["KeySchema"], key=lambda key: key["KeyType"])
    if keys != AUDIT_KEY_SCHEMA:
        raise AuditPersistenceError("Audit table has an incompatible key schema.")
    attributes = {a["AttributeName"]: a["AttributeType"] for a in table["AttributeDefinitions"]}
    if attributes.get("business_id") != "S" or attributes.get("entry_id") != "S":
        raise AuditPersistenceError("Audit table keys must be strings.")


def get_audit_entry(
    business_id: str, entry_id: str, settings: Settings | None = None
) -> AuditEntry | None:
    """Read one persisted event consistently before reprocessing an assessment."""
    resolved = settings or Settings.from_environment()
    try:
        response = _table(resolved).get_item(
            Key={"business_id": business_id, "entry_id": entry_id}, ConsistentRead=True
        )
        raw = response.get("Item")
        return None if raw is None else AuditEntry.model_validate(raw)
    except (BotoCoreError, ClientError, ValueError, TypeError) as error:
        raise AuditPersistenceError(
            "Audit read failed; processing cannot be acknowledged."
        ) from error


def append_audit_entry(entry: AuditEntry, settings: Settings | None = None) -> AuditAppendResult:
    """Insert once using a conditional put, returning the persisted first event.

    A retry or racing caller receives the original row, never an overwrite. The
    first decision is authoritative for this assessment identity; changed input
    or policy requires a different assessment_id. This is audit idempotency, not
    an exactly-once notification guarantee.
    """
    resolved = settings or Settings.from_environment()
    # Revalidate even a model_copy/model_construct supplied by another caller.
    validated = AuditEntry.model_validate(entry.model_dump(mode="python"))
    try:
        _table(resolved).put_item(
            Item=validated.model_dump(mode="json"),
            ConditionExpression="attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            ExpressionAttributeNames={"#pk": "business_id", "#sk": "entry_id"},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise AuditPersistenceError(
                "Audit append failed; decision was not acknowledged."
            ) from error
        existing = get_audit_entry(validated.business_id, validated.entry_id, resolved)
        if existing is None:
            raise AuditPersistenceError("Duplicate audit key could not be read back.") from error
        identity_fields = (
            "assessment_id",
            "event",
            "alert_id",
            "alert_modified",
            "source_url",
            "policy_version",
            "model_id",
            "mode",
        )
        if any(getattr(existing, field) != getattr(validated, field) for field in identity_fields):
            raise AuditPersistenceError("Audit key collision has incompatible identity fields.")
        return AuditAppendResult(entry=existing, created=False)
    except BotoCoreError as error:
        raise AuditPersistenceError("Audit append outcome is unknown; retry safely.") from error
    logger.info(
        "audit_appended business=%s alert=%s event=%s decision=%s entry=%s",
        validated.business_id,
        validated.alert_id,
        validated.event.value,
        validated.decision.value,
        validated.entry_id,
    )
    return AuditAppendResult(entry=validated, created=True)


def list_history(
    business_id: str, settings: Settings | None = None, *, page_size: int = 100
) -> list[HistoryRecord]:
    """Query every page for one business; return records in timestamp order."""
    if not business_id.strip() or page_size < 1:
        raise ValueError("A business_id and positive page_size are required.")
    resolved = settings or Settings.from_environment()
    entries: list[HistoryRecord] = []
    try:
        table = _table(resolved)
        response = table.query(
            KeyConditionExpression=Key("business_id").eq(business_id),
            ConsistentRead=True,
            Limit=page_size,
        )
        while True:
            entries.extend(
                HISTORY_ADAPTER.validate_python(raw) for raw in response.get("Items", [])
            )
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            response = table.query(
                KeyConditionExpression=Key("business_id").eq(business_id),
                ConsistentRead=True,
                Limit=page_size,
                ExclusiveStartKey=last_key,
            )
    except (BotoCoreError, ClientError, ValueError, TypeError) as error:
        raise AuditPersistenceError("Audit history could not be read completely.") from error
    return sorted(entries, key=lambda entry: (entry.timestamp, entry.entry_id))


def list_audit_entries(
    business_id: str, settings: Settings | None = None, *, page_size: int = 100
) -> list[AuditEntry]:
    """Return recall records after validating the complete mixed history."""
    return [
        row
        for row in list_history(business_id, settings, page_size=page_size)
        if isinstance(row, AuditEntry)
    ]


def get_diary_record(
    business_id: str, entry_id: str, settings: Settings | None = None
) -> DiaryRecord | None:
    """Consistently read one diary fact; never coerce a recall row into a diary."""
    resolved = settings or Settings.from_environment()
    try:
        raw = (
            _table(resolved)
            .get_item(Key={"business_id": business_id, "entry_id": entry_id}, ConsistentRead=True)
            .get("Item")
        )
        return None if raw is None else DiaryRecord.model_validate(raw)
    except (BotoCoreError, ClientError, ValueError, TypeError) as error:
        raise AuditPersistenceError("Diary evidence could not be read.") from error


def append_diary_record(record: DiaryRecord, settings: Settings | None = None) -> DiaryAppendResult:
    """Insert an immutable daily fact, returning the stored winner on retry."""
    resolved = settings or Settings.from_environment()
    validated = DiaryRecord.model_validate(record.model_dump(mode="python"))
    if validated.event is DiaryEvent.CONFIRMED:
        filed = get_diary_record(validated.business_id, diary_id(validated.entry_date), resolved)
        if filed is None or filed.event is not DiaryEvent.FILED:
            raise ValueError("File the diary before recording owner confirmation.")
        if validated.timestamp < filed.timestamp:
            raise ValueError("Confirmation cannot precede filing.")
    try:
        _table(resolved).put_item(
            Item=validated.model_dump(mode="json"),
            ConditionExpression="attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            ExpressionAttributeNames={"#pk": "business_id", "#sk": "entry_id"},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise AuditPersistenceError("Diary append failed; no success acknowledged.") from error
        existing = get_diary_record(validated.business_id, validated.entry_id, resolved)
        if existing is None or (existing.event, existing.entry_date) != (
            validated.event,
            validated.entry_date,
        ):
            raise AuditPersistenceError("Diary key collision could not be reconciled.") from error
        return DiaryAppendResult(record=existing, created=False)
    except BotoCoreError as error:
        raise AuditPersistenceError(
            "Diary append outcome unknown; retry the same identity."
        ) from error
    return DiaryAppendResult(record=validated, created=True)
