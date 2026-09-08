"""The first local AllerGuard Strands agent."""

from __future__ import annotations

from strands import Agent
from strands.models import BedrockModel

from src.config import Settings
from src.tools.current_time import get_current_utc_time

SYSTEM_PROMPT = """
You are AllerGuard, a food-safety monitoring assistant for small UK food businesses.

This is a local readiness demonstration. Before replying, you must call the
get_current_utc_time tool exactly once.

After receiving the tool result, reply in two short sentences:
1. Confirm that AllerGuard is online and include the UTC time returned by the tool.
2. Explain that future AllerGuard runs will monitor FSA food recalls and raise
   only decisions that require human attention.

Do not claim that you checked live recalls, inventory, escalations, or an audit
trail. Those features are not implemented yet.
""".strip()


def build_hello_agent(settings: Settings | None = None) -> Agent:
    """Create the local Feature 4 Hello agent."""
    resolved_settings = settings or Settings.from_environment()

    model = BedrockModel(
        model_id=resolved_settings.bedrock_model_id,
        region_name=resolved_settings.aws_region,
    )

    return Agent(
        model=model,
        tools=[get_current_utc_time],
        system_prompt=SYSTEM_PROMPT,
    )
