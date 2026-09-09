"""Central configuration for AllerGuard."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_AWS_REGION = "eu-west-2"
DEFAULT_BEDROCK_MODEL_ID = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_DYNAMODB_TABLE_BUSINESSES = "allerguard-businesses"

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

    fsa_mode: Literal["live", "replay"] = DEFAULT_FSA_MODE
    fsa_base_uri: str = Field(default=DEFAULT_FSA_BASE_URI, min_length=1)
    fsa_fixtures_path: Path = DEFAULT_FSA_FIXTURES_PATH

    @classmethod
    def from_environment(cls) -> "Settings":
        """Build settings from environment variables with safe project defaults."""
        return cls(
            aws_region=os.environ.get("AWS_REGION", DEFAULT_AWS_REGION),
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
