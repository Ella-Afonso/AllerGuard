"""Immutable escalation and owner-decision facts; current status is a read projection."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError

from src.config import Settings
from src.domain.models import (
    ActionPack,
    AuditEntry,
    AuditEvent,
    DecisionAppendResult,
    DecisionRecord,
    Escalation,
    EscalationAppendResult,
    EscalationStatus,
    EscalationView,
    GateDecision,
    OwnerDecision,
)
from src.tools import audit

logger = logging.getLogger(__name__)
ESCALATION_KEY_SCHEMA = [
    {"AttributeName": "business_id", "KeyType": "HASH"},
    {"AttributeName": "escalation_id", "KeyType": "RANGE"},
]


class EscalationPersistenceError(RuntimeError):
    """No queued outcome can be acknowledged; caller must surface and retry."""

    decision = GateDecision.ESCALATE


def _table(settings: Settings) -> Any:
    """Dynamic boto3 Table proxy; AWS shapes stop at this tool boundary."""
    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(
        settings.dynamodb_table_escalations
    )


def ensure_escalation_table(settings: Settings | None = None) -> None:
    """Provision the escalation table explicitly, including safe concurrent creation.

    Runtime reads/writes never create tables. Setup permissions belong to the
    operator; a runtime identity only needs GetItem, Query, and PutItem.
    """
    resolved = settings or Settings.from_environment()
    client = boto3.client("dynamodb", region_name=resolved.aws_region)
    name = resolved.dynamodb_table_escalations
    try:
        client.describe_table(TableName=name)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        try:
            client.create_table(
                TableName=name,
                KeySchema=ESCALATION_KEY_SCHEMA,
                AttributeDefinitions=[
                    {"AttributeName": "business_id", "AttributeType": "S"},
                    {"AttributeName": "escalation_id", "AttributeType": "S"},
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
    if keys != ESCALATION_KEY_SCHEMA:
        raise EscalationPersistenceError("Escalation table has an incompatible key schema.")
    attributes = {a["AttributeName"]: a["AttributeType"] for a in table["AttributeDefinitions"]}
    if attributes.get("business_id") != "S" or attributes.get("escalation_id") != "S":
        raise EscalationPersistenceError("Escalation table keys must be strings.")


def get_escalation(
    business_id: str, escalation_id: str, settings: Settings | None = None
) -> Escalation | None:
    """Read one persisted queue row consistently before drafting or retrying."""
    resolved = settings or Settings.from_environment()
    _validate_key(business_id, escalation_id)
    try:
        response = _table(resolved).get_item(
            Key={"business_id": business_id, "escalation_id": escalation_id},
            ConsistentRead=True,
        )
        raw = response.get("Item")
        result = None if raw is None else Escalation.model_validate(raw)
        if result is not None and (
            result.business_id != business_id or result.escalation_id != escalation_id
        ):
            raise ValueError("Stored queue identity differs from the requested key.")
        return result
    except (BotoCoreError, ClientError, ValueError, TypeError) as error:
        raise EscalationPersistenceError(
            "Escalation read failed; processing cannot be acknowledged."
        ) from error


def queue_escalation(
    escalation: Escalation, settings: Settings | None = None
) -> EscalationAppendResult:
    """Insert once using a conditional put, returning the persisted first row.

    A retry or racing caller receives the original pack and timestamp, never an
    overwrite. Matching identity fields reuse the stored row; a collision with
    different identity is an error.
    """
    resolved = settings or Settings.from_environment()
    validated = Escalation.model_validate(escalation.model_dump(mode="python"))
    try:
        _table(resolved).put_item(
            Item=validated.model_dump(mode="json"),
            ConditionExpression="attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            ExpressionAttributeNames={"#pk": "business_id", "#sk": "escalation_id"},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise EscalationPersistenceError(
                "Escalation queue failed; outcome was not acknowledged."
            ) from error
        existing = get_escalation(validated.business_id, validated.escalation_id, resolved)
        if existing is None:
            raise EscalationPersistenceError(
                "Duplicate escalation key could not be read back."
            ) from error
        identity_fields = (
            "assessment_id",
            "alert_id",
            "alert_modified",
            "source_url",
            "policy_version",
        )
        if any(getattr(existing, field) != getattr(validated, field) for field in identity_fields):
            raise EscalationPersistenceError(
                "Escalation key collision has incompatible identity fields."
            )
        return EscalationAppendResult(escalation=existing, created=False)
    except BotoCoreError as error:
        raise EscalationPersistenceError(
            "Escalation queue outcome is unknown; retry safely."
        ) from error
    logger.info(
        "escalation_queued business=%s alert=%s escalation=%s draft_source=%s",
        validated.business_id,
        validated.alert_id,
        validated.escalation_id,
        validated.draft_source.value,
    )
    return EscalationAppendResult(escalation=validated, created=True)


def list_pending(
    business_id: str, settings: Settings | None = None, *, page_size: int = 100
) -> list[Escalation]:
    """Derive pending rows from all pages of immutable queue and decision facts."""
    return [
        view.escalation
        for view in list_escalation_views(business_id, settings, page_size=page_size)
        if view.effective_status is EscalationStatus.PENDING
    ]


def _validate_key(business_id: str, escalation_id: str) -> None:
    if not business_id.strip() or not re.fullmatch(r"[0-9a-f]{64}", escalation_id):
        raise ValueError("A business ID and bare 64-character escalation ID are required.")


def _decode_decision(raw: dict[str, Any]) -> DecisionRecord:
    """DynamoDB metadata stays at this boundary; models use the bare ID."""
    key = raw.get("escalation_id")
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}#decision", key):
        raise ValueError("Invalid stored decision key.")
    return DecisionRecord.model_validate(raw | {"escalation_id": key.removesuffix("#decision")})


def get_decision(
    business_id: str, escalation_id: str, settings: Settings | None = None
) -> DecisionRecord | None:
    """Read the first owner choice consistently without writing or repairing."""
    _validate_key(business_id, escalation_id)
    resolved = settings or Settings.from_environment()
    try:
        raw = (
            _table(resolved)
            .get_item(
                Key={"business_id": business_id, "escalation_id": f"{escalation_id}#decision"},
                ConsistentRead=True,
            )
            .get("Item")
        )
        result = None if raw is None else _decode_decision(raw)
        if result is not None and (
            result.business_id != business_id or result.escalation_id != escalation_id
        ):
            raise ValueError("Stored decision identity differs from the requested key.")
        return result
    except (BotoCoreError, ClientError, ValueError, TypeError) as error:
        raise EscalationPersistenceError("Owner decision could not be read reliably.") from error


def get_escalation_view(
    business_id: str, escalation_id: str, settings: Settings | None = None
) -> EscalationView | None:
    """Read effective status while preserving the original pending fact."""
    resolved = settings or Settings.from_environment()
    queued = get_escalation(business_id, escalation_id, resolved)
    decision = get_decision(business_id, escalation_id, resolved)
    if queued is None:
        if decision is not None:
            raise EscalationPersistenceError("Owner decision has no original queue record.")
        return None
    try:
        return EscalationView(escalation=queued, decision_record=decision)
    except ValueError as error:
        raise EscalationPersistenceError("Queue and owner decision evidence disagree.") from error


def list_escalation_views(
    business_id: str, settings: Settings | None = None, *, page_size: int = 100
) -> list[EscalationView]:
    """Read every page before projecting status; malformed/orphan rows fail visibly."""
    if not business_id.strip() or page_size < 1:
        raise ValueError("A business_id and positive page_size are required.")
    resolved = settings or Settings.from_environment()
    rows: dict[str, Escalation] = {}
    decisions: dict[str, DecisionRecord] = {}
    try:
        table = _table(resolved)
        response = table.query(
            KeyConditionExpression=Key("business_id").eq(business_id),
            ConsistentRead=True,
            Limit=page_size,
        )
        while True:
            for raw in response.get("Items", []):
                key = raw.get("escalation_id")
                if raw.get("business_id") != business_id or not isinstance(key, str):
                    raise ValueError("Stored row has an incompatible business or key.")
                if re.fullmatch(r"[0-9a-f]{64}", key):
                    rows[key] = Escalation.model_validate(raw)
                elif re.fullmatch(r"[0-9a-f]{64}#decision", key):
                    record = _decode_decision(raw)
                    decisions[record.escalation_id] = record
                else:
                    raise ValueError("Unknown escalation-table record type.")
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            response = table.query(
                KeyConditionExpression=Key("business_id").eq(business_id),
                ConsistentRead=True,
                Limit=page_size,
                ExclusiveStartKey=last_key,
            )
        if decisions.keys() - rows.keys():
            raise ValueError("Owner decision has no original queue record.")
        views = [
            EscalationView(escalation=row, decision_record=decisions.get(key))
            for key, row in rows.items()
        ]
    except (BotoCoreError, ClientError, ValueError, TypeError) as error:
        raise EscalationPersistenceError(
            "Escalation queue could not be read completely."
        ) from error
    return sorted(
        views, key=lambda view: (view.escalation.queued_at, view.escalation.escalation_id)
    )


def get_queued_evidence(escalation: Escalation, settings: Settings) -> AuditEntry:
    """Require persisted queued-audit provenance before notification or owner choice."""
    evidence = audit.get_audit_entry(
        escalation.business_id, f"{escalation.assessment_id}#escalation_queued", settings
    )
    if evidence is None or evidence.event is not AuditEvent.ESCALATION_QUEUED:
        raise audit.AuditPersistenceError("Escalation has no queued audit evidence.")
    fields = (
        "business_id",
        "assessment_id",
        "alert_id",
        "alert_modified",
        "alert_title",
        "source_url",
        "tier",
        "floor_tier",
        "reason",
        "policy_version",
        "draft_source",
    )
    if any(getattr(evidence, field) != getattr(escalation, field) for field in fields):
        raise audit.AuditPersistenceError("Queued audit does not match the stored escalation.")
    return evidence


def record_decision(
    business_id: str,
    escalation_id: str,
    decision: OwnerDecision,
    edited_pack: ActionPack | None = None,
    *,
    decided_at: datetime,
    settings: Settings | None = None,
) -> DecisionAppendResult:
    """Append one owner choice, then acknowledge or repair its linked audit.

    A conflicting later choice returns the stored first decision. This is a
    trusted owner boundary, deliberately not exposed as a model-callable tool.
    Notification success is not a prerequisite for making an owner decision.
    """
    resolved = settings or Settings.from_environment()
    queued = get_escalation(business_id, escalation_id, resolved)
    if queued is None:
        raise ValueError("Escalation does not exist for this business.")
    proposed = DecisionRecord(
        business_id=business_id,
        escalation_id=escalation_id,
        assessment_id=queued.assessment_id,
        decision=decision,
        decided_at=decided_at,
        original_action_pack=queued.action_pack,
        edited_pack=edited_pack,
    )
    EscalationView(escalation=queued, decision_record=proposed)
    evidence = get_queued_evidence(queued, resolved)
    stored = get_decision(business_id, escalation_id, resolved)
    created = False
    if stored is None:
        try:
            _table(resolved).put_item(
                Item=proposed.model_dump(mode="json")
                | {"escalation_id": f"{escalation_id}#decision"},
                ConditionExpression="attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
                ExpressionAttributeNames={"#pk": "business_id", "#sk": "escalation_id"},
            )
            stored, created = proposed, True
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise EscalationPersistenceError(
                    "Owner choice could not be acknowledged."
                ) from error
            stored = get_decision(business_id, escalation_id, resolved)
            if stored is None:
                raise EscalationPersistenceError(
                    "Winning owner choice could not be read."
                ) from error
        except BotoCoreError as error:
            raise EscalationPersistenceError(
                "Owner choice outcome is unknown; retry the same ID."
            ) from error
    try:
        EscalationView(escalation=queued, decision_record=stored)
    except ValueError as error:
        raise EscalationPersistenceError("Stored owner choice contradicts the queue.") from error
    # Deliberately outside the conditional insert: a retry repairs missing audit
    # using the WINNING choice and time, never the caller's new proposal.
    audit_entry = AuditEntry.model_validate(
        evidence.model_dump(mode="python")
        | {
            "event": AuditEvent.DECISION_RECORDED,
            "entry_id": f"{escalation_id}#decision_recorded",
            "timestamp": stored.decided_at,
            "owner_decision": stored.model_dump(mode="python"),
        }
    )
    recorded = audit.append_audit_entry(audit_entry, resolved)
    return DecisionAppendResult(record=stored, created=created, audit=recorded)
