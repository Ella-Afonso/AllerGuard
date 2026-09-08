"""AWS Lambda entry point for scheduled AllerGuard AgentCore invocation."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from src.config import Settings
from src.tools.agentcore_runtime import invoke_agentcore_runtime

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULED_PROMPT = (
    "Run the AllerGuard scheduled readiness check. Call the time tool before replying."
)


def get_scheduled_prompt(event: Mapping[str, object]) -> str:
    """Return a safe scheduled prompt, allowing an optional non-empty override."""
    candidate = event.get("prompt")

    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()

    return DEFAULT_SCHEDULED_PROMPT


def lambda_handler(event: Mapping[str, object], _context: object) -> None:
    """Invoke the deployed Hello agent from an EventBridge Scheduler event."""
    settings = Settings.from_environment()

    if not settings.agentcore_runtime_arn:
        raise RuntimeError("ALLERGUARD_AGENTCORE_RUNTIME_ARN must be configured")

    prompt = get_scheduled_prompt(event)

    logger.info("Starting scheduled AllerGuard AgentCore invocation")

    response_text = invoke_agentcore_runtime(
        prompt=prompt,
        runtime_arn=settings.agentcore_runtime_arn,
        region=settings.aws_region,
    )

    logger.info(
        "Scheduled AllerGuard AgentCore invocation finished; response_length=%d",
        len(response_text),
    )
