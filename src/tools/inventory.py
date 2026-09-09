"""DynamoDB persistence for the fictional AllerGuard demo business."""

from __future__ import annotations

import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError
from strands import tool

from src.config import Settings
from src.domain.models import BusinessProfile

logger = logging.getLogger(__name__)

BUSINESS_PARTITION_KEY = "business_id"


def _table(settings: Settings) -> Any:
    """Return the configured DynamoDB table.

    boto3 creates a dynamic Table proxy, so its static type is not useful here.
    Raw DynamoDB data remains private to this module and is converted to a
    BusinessProfile before leaving the boundary.
    """
    return boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
    ).Table(settings.dynamodb_table_businesses)


def ensure_business_table(settings: Settings | None = None) -> None:
    """Create the business table if it does not already exist."""
    resolved_settings = settings or Settings.from_environment()
    client = boto3.client(
        "dynamodb",
        region_name=resolved_settings.aws_region,
    )

    try:
        client.describe_table(
            TableName=resolved_settings.dynamodb_table_businesses,
        )
        return
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")

        if error_code != "ResourceNotFoundException":
            raise

    client.create_table(
        TableName=resolved_settings.dynamodb_table_businesses,
        KeySchema=[
            {
                "AttributeName": BUSINESS_PARTITION_KEY,
                "KeyType": "HASH",
            }
        ],
        AttributeDefinitions=[
            {
                "AttributeName": BUSINESS_PARTITION_KEY,
                "AttributeType": "S",
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    client.get_waiter("table_exists").wait(
        TableName=resolved_settings.dynamodb_table_businesses,
    )

    logger.info(
        "Created DynamoDB business table; table=%s region=%s",
        resolved_settings.dynamodb_table_businesses,
        resolved_settings.aws_region,
    )


@tool
def get_business(business_id: str) -> BusinessProfile | None:
    """Return one business profile from DynamoDB.

    Use this tool when the monitoring workflow needs the fictional business's
    typed inventory before matching a Food Standards Agency alert. This tool
    only reads the business profile; it does not fetch alerts, perform matching,
    decide escalation, or write audit records.
    """
    if not business_id.strip():
        raise ValueError("business_id must not be empty.")

    settings = Settings.from_environment()
    response = _table(settings).get_item(
        Key={BUSINESS_PARTITION_KEY: business_id},
    )

    raw_item = response.get("Item")

    if raw_item is None:
        return None

    profile = BusinessProfile.model_validate(raw_item)

    logger.info(
        "Loaded business profile; business_id=%s inventory_count=%d",
        profile.business_id,
        len(profile.inventory),
    )

    return profile


@tool
def seed_business(profile: BusinessProfile) -> None:
    """Create or replace one typed business profile in DynamoDB.

    This operation is idempotent for the same business_id. It is used by the
    local seed script and tests to create the fictional demo business.
    """
    if not profile.business_id.strip():
        raise ValueError("profile.business_id must not be empty.")

    settings = Settings.from_environment()
    item = profile.model_dump(mode="python")

    _table(settings).put_item(Item=item)

    logger.info(
        "Stored business profile; business_id=%s inventory_count=%d",
        profile.business_id,
        len(profile.inventory),
    )
