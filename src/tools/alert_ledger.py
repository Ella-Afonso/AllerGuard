"""DynamoDB ledger for processed FSA alert versions and the poll watermark."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError
from strands import tool

from src.config import Settings
from src.domain.dedup import filter_unseen_alerts
from src.domain.models import Alert, SeenAlertVersion
from src.tools.fsa_api import load_alerts

logger = logging.getLogger(__name__)

ALERT_ID_PARTITION_KEY = "alert_id"
MODIFIED_SORT_KEY = "modified"

WATERMARK_ALERT_ID = "_watermark"
WATERMARK_SORT_KEY = "_watermark"
WATERMARK_ATTRIBUTE = "watermark"


def _table(settings: Settings) -> Any:
    """Return the configured DynamoDB alert-ledger table."""
    return boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
    ).Table(settings.dynamodb_table_alerts_seen)


def _normalise_timestamp(value: str) -> str:
    """Validate a timezone-aware timestamp and store it as UTC ending in Z."""
    try:
        parsed_value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("watermark must be an ISO 8601 timestamp with a timezone.") from error

    if parsed_value.tzinfo is None:
        raise ValueError("watermark must include a timezone, for example 2026-09-09T12:00:00Z.")

    return parsed_value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _timestamp_for_storage(value: datetime) -> str:
    """Convert one timezone-aware datetime to DynamoDB's UTC string form."""
    if value.tzinfo is None:
        raise ValueError("Alert modified timestamps must include a timezone.")

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def ensure_alerts_seen_table(settings: Settings | None = None) -> None:
    """Create the alerts-seen ledger table if it does not already exist."""
    resolved_settings = settings or Settings.from_environment()

    client = boto3.client(
        "dynamodb",
        region_name=resolved_settings.aws_region,
    )

    try:
        client.describe_table(
            TableName=resolved_settings.dynamodb_table_alerts_seen,
        )
        return
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")

        if error_code != "ResourceNotFoundException":
            raise

    client.create_table(
        TableName=resolved_settings.dynamodb_table_alerts_seen,
        KeySchema=[
            {
                "AttributeName": ALERT_ID_PARTITION_KEY,
                "KeyType": "HASH",
            },
            {
                "AttributeName": MODIFIED_SORT_KEY,
                "KeyType": "RANGE",
            },
        ],
        AttributeDefinitions=[
            {
                "AttributeName": ALERT_ID_PARTITION_KEY,
                "AttributeType": "S",
            },
            {
                "AttributeName": MODIFIED_SORT_KEY,
                "AttributeType": "S",
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    client.get_waiter("table_exists").wait(
        TableName=resolved_settings.dynamodb_table_alerts_seen,
    )

    logger.info(
        "Created alert ledger table; table=%s region=%s",
        resolved_settings.dynamodb_table_alerts_seen,
        resolved_settings.aws_region,
    )


def list_seen_versions(
    settings: Settings | None = None,
) -> list[SeenAlertVersion]:
    """Return all processed alert versions, excluding the reserved watermark item."""
    resolved_settings = settings or Settings.from_environment()
    table = _table(resolved_settings)

    seen_versions: list[SeenAlertVersion] = []
    response = table.scan(ConsistentRead=True)

    while True:
        for raw_item in response.get("Items", []):
            if not isinstance(raw_item, dict):
                raise ValueError("Alert ledger returned an invalid DynamoDB item.")

            alert_id = raw_item.get(ALERT_ID_PARTITION_KEY)
            modified = raw_item.get(MODIFIED_SORT_KEY)

            if alert_id == WATERMARK_ALERT_ID:
                continue

            if not isinstance(alert_id, str) or not isinstance(modified, str):
                raise ValueError("Alert ledger item is missing its alert version key.")

            try:
                modified_datetime = datetime.fromisoformat(modified.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("Alert ledger item has an invalid modified timestamp.") from error

            if modified_datetime.tzinfo is None:
                raise ValueError("Alert ledger modified timestamps must include a timezone.")

            seen_versions.append(
                SeenAlertVersion(
                    alert_id=alert_id,
                    modified=modified_datetime,
                )
            )

        last_evaluated_key = response.get("LastEvaluatedKey")

        if last_evaluated_key is None:
            break

        response = table.scan(
            ExclusiveStartKey=last_evaluated_key,
            ConsistentRead=True,
        )

    return seen_versions


def read_alert_watermark(settings: Settings | None = None) -> str | None:
    """Return the timestamp of the last fully processed alert batch."""
    resolved_settings = settings or Settings.from_environment()

    response = _table(resolved_settings).get_item(
        Key={
            ALERT_ID_PARTITION_KEY: WATERMARK_ALERT_ID,
            MODIFIED_SORT_KEY: WATERMARK_SORT_KEY,
        },
        ConsistentRead=True,
    )

    raw_item = response.get("Item")

    if raw_item is None:
        return None

    watermark = raw_item.get(WATERMARK_ATTRIBUTE)

    if not isinstance(watermark, str):
        raise ValueError("Alert ledger watermark item is invalid.")

    return _normalise_timestamp(watermark)


@tool
def get_new_alerts() -> list[Alert]:
    """Return unseen Food Standards Agency alert versions.

    This tool loads alerts through AllerGuard's configured live or replay source,
    checks exact (alert ID, modified timestamp) versions against the DynamoDB
    ledger, and returns only unseen versions in the original newest-first order.

    Do not judge relevance, match inventory, draft a response, or write to the
    ledger. Passing every unseen alert downstream is the safety requirement.
    """
    return load_new_alerts(Settings.from_environment())


def load_new_alerts(settings: Settings) -> list[Alert]:
    """Use one explicit configuration for the source and its version ledger."""
    watermark = read_alert_watermark(settings)
    since = watermark
    if since is None and settings.fsa_mode == "live" and settings.fsa_initial_since is not None:
        since = settings.fsa_initial_since.astimezone(UTC).isoformat().replace("+00:00", "Z")
    alerts = load_alerts(settings, since=since)

    seen_versions = {(seen.alert_id, seen.modified) for seen in list_seen_versions(settings)}

    new_alerts = filter_unseen_alerts(alerts, seen_versions)

    logger.info(
        "Loaded unseen FSA alert versions; watermark=%s count=%d",
        watermark or "not-set",
        len(new_alerts),
    )

    return new_alerts


def commit_processed_batch(
    watermark: str,
    alerts: list[Alert],
    settings: Settings | None = None,
) -> None:
    """Record a fully processed batch, then advance its watermark.

    This is deliberately not a Strands tool. It must be called only after every
    alert in the batch has completed downstream matching, gate, and audit work.
    The deterministic runtime cycle is its production caller. Writes are serial,
    not transactional: failure may leave seen rows without an advanced watermark.
    """
    if not alerts:
        return

    resolved_settings = settings or Settings.from_environment()
    normalised_watermark = _normalise_timestamp(watermark)

    latest_alert_modified = max(alert.modified for alert in alerts)

    if datetime.fromisoformat(normalised_watermark) < latest_alert_modified:
        raise ValueError("watermark cannot be earlier than the newest processed alert version.")

    previous = read_alert_watermark(resolved_settings)
    if previous is not None and datetime.fromisoformat(previous) > datetime.fromisoformat(
        normalised_watermark
    ):
        normalised_watermark = previous

    table = _table(resolved_settings)

    for alert in alerts:
        table.put_item(
            Item={
                ALERT_ID_PARTITION_KEY: alert.id,
                MODIFIED_SORT_KEY: _timestamp_for_storage(alert.modified),
            }
        )

    table.put_item(
        Item={
            ALERT_ID_PARTITION_KEY: WATERMARK_ALERT_ID,
            MODIFIED_SORT_KEY: WATERMARK_SORT_KEY,
            WATERMARK_ATTRIBUTE: normalised_watermark,
        }
    )

    logger.info(
        "Committed processed alert batch; count=%d watermark=%s",
        len(alerts),
        normalised_watermark,
    )
