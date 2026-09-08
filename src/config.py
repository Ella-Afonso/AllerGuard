"""Central configuration for AllerGuard."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

DEFAULT_AWS_REGION = "eu-west-2"
DEFAULT_BEDROCK_MODEL_ID = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"


class Settings(BaseModel):
    """Non-secret runtime configuration for AllerGuard."""

    aws_region: str = Field(min_length=1)
    bedrock_model_id: str = Field(min_length=1)

    @classmethod
    def from_environment(cls) -> "Settings":
        """Build settings from environment variables with safe project defaults."""
        return cls(
            aws_region=os.environ.get("AWS_REGION", DEFAULT_AWS_REGION),
            bedrock_model_id=os.environ.get(
                "ALLERGUARD_BEDROCK_MODEL_ID",
                DEFAULT_BEDROCK_MODEL_ID,
            ),
        )
