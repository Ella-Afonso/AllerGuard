"""Central configuration for AllerGuard."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal, Self, cast

from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_AWS_REGION = "eu-west-2"
DEFAULT_BEDROCK_MODEL_ID = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_DYNAMODB_TABLE_BUSINESSES = "allerguard-businesses"
DEFAULT_DYNAMODB_TABLE_ALERTS_SEEN = "allerguard-alerts-seen"
DEFAULT_DYNAMODB_TABLE_AUDIT = "allerguard-audit"
DEFAULT_DYNAMODB_TABLE_ESCALATIONS = "allerguard-escalations"

DEFAULT_FSA_MODE: Literal["live", "replay"] = "replay"
DEFAULT_FSA_BASE_URI = "https://data.food.gov.uk/food-alerts"
DEFAULT_FSA_FIXTURES_PATH = Path("fixtures/alerts_recent.json")


def _read_fsa_mode() -> Literal["live", "replay"]:
    """Read and validate the configured FSA source mode."""
    mode = os.environ.get(
        "ALLERGUARD_FSA_MODE",
        DEFAULT_FSA_MODE,
    ).lower()

    if mode == "live":
        return "live"

    if mode == "replay":
        return "replay"

    raise ValueError("ALLERGUARD_FSA_MODE must be either 'live' or 'replay'.")


class Settings(BaseModel):
    """Non-secret runtime configuration for AllerGuard."""

    aws_region: str = Field(min_length=1)
    bedrock_model_id: str = Field(min_length=1)
    agentcore_runtime_arn: str | None = None

    dynamodb_table_businesses: str = Field(
        default=DEFAULT_DYNAMODB_TABLE_BUSINESSES,
        min_length=1,
    )

    dynamodb_table_alerts_seen: str = Field(
        default=DEFAULT_DYNAMODB_TABLE_ALERTS_SEEN,
        min_length=1,
    )
    dynamodb_table_audit: str = Field(default=DEFAULT_DYNAMODB_TABLE_AUDIT, min_length=1)
    dynamodb_table_escalations: str = Field(
        default=DEFAULT_DYNAMODB_TABLE_ESCALATIONS,
        min_length=1,
    )

    fsa_mode: Literal["live", "replay"] = DEFAULT_FSA_MODE
    fsa_base_uri: str = Field(default=DEFAULT_FSA_BASE_URI, min_length=1)
    fsa_fixtures_path: Path = DEFAULT_FSA_FIXTURES_PATH

    notification_mode: Literal["disabled", "ses", "sns", "log"] = "disabled"
    ses_from_email: str | None = Field(default=None, repr=False)
    owner_email: str | None = Field(default=None, repr=False)
    sns_topic_arn: str | None = Field(default=None, repr=False)

    @field_validator("ses_from_email", "owner_email")
    @classmethod
    def plain_email_address(cls, value: str | None) -> str | None:
        """Only a configured single ASCII address; never header text or a list."""
        if value is None:
            return None
        if not value.isascii() or not re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+", value):
            raise ValueError("Notification email must be a single plain address.")
        return value

    @model_validator(mode="after")
    def notification_configuration(self) -> Self:
        if self.notification_mode == "ses" and (not self.ses_from_email or not self.owner_email):
            raise ValueError("SES mode requires configured sender and owner addresses.")
        if self.notification_mode == "sns" and not self.sns_topic_arn:
            raise ValueError("SNS mode requires a configured topic.")
        if self.sns_topic_arn is not None:
            if not re.fullmatch(
                r"arn:aws[a-z-]*:sns:[a-z0-9-]+:\d{12}:[A-Za-z0-9_-]+", self.sns_topic_arn
            ):
                raise ValueError("Notification topic must be a standard SNS topic ARN.")
            if self.sns_topic_arn.split(":")[3] != self.aws_region:
                raise ValueError("Notification topic must use the configured AWS region.")
        return self

    @classmethod
    def from_environment(cls) -> "Settings":
        """Build settings from environment variables with safe project defaults."""
        notification_mode = os.environ.get("ALLERGUARD_NOTIFICATION_MODE", "disabled")
        return cls(
            aws_region=os.environ.get("AWS_REGION", DEFAULT_AWS_REGION),
            notification_mode=cast(Literal["disabled", "ses", "sns", "log"], notification_mode),
            ses_from_email=os.environ.get("ALLERGUARD_SES_FROM_EMAIL"),
            owner_email=os.environ.get("ALLERGUARD_OWNER_EMAIL"),
            sns_topic_arn=os.environ.get("ALLERGUARD_SNS_TOPIC_ARN"),
            bedrock_model_id=os.environ.get(
                "ALLERGUARD_BEDROCK_MODEL_ID",
                DEFAULT_BEDROCK_MODEL_ID,
            ),
            agentcore_runtime_arn=os.environ.get(
                "ALLERGUARD_AGENTCORE_RUNTIME_ARN",
            ),
            dynamodb_table_businesses=os.environ.get(
                "ALLERGUARD_DYNAMODB_TABLE_BUSINESSES",
                DEFAULT_DYNAMODB_TABLE_BUSINESSES,
            ),
            dynamodb_table_alerts_seen=os.environ.get(
                "ALLERGUARD_DYNAMODB_TABLE_ALERTS_SEEN",
                DEFAULT_DYNAMODB_TABLE_ALERTS_SEEN,
            ),
            dynamodb_table_audit=os.environ.get(
                "ALLERGUARD_DYNAMODB_TABLE_AUDIT", DEFAULT_DYNAMODB_TABLE_AUDIT
            ),
            dynamodb_table_escalations=os.environ.get(
                "ALLERGUARD_DYNAMODB_TABLE_ESCALATIONS",
                DEFAULT_DYNAMODB_TABLE_ESCALATIONS,
            ),
            fsa_mode=_read_fsa_mode(),
            fsa_base_uri=os.environ.get(
                "ALLERGUARD_FSA_BASE_URI",
                DEFAULT_FSA_BASE_URI,
            ),
            fsa_fixtures_path=Path(
                os.environ.get(
                    "ALLERGUARD_FSA_FIXTURES_PATH",
                    str(DEFAULT_FSA_FIXTURES_PATH),
                )
            ),
        )
