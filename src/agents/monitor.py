"""The AllerGuard Monitor agent."""

from __future__ import annotations

from strands import Agent
from strands.models import BedrockModel

from src.config import Settings
from src.tools.alert_ledger import get_new_alerts

SYSTEM_PROMPT = """
You are AllerGuard's Monitor agent.

Call get_new_alerts exactly once. Return the alerts it provides so that the
supervisor can pass every one downstream for matching.

Your responsibility is completeness. You must not judge whether an alert is
relevant to a business, decide whether to notify an owner, draft advice, or
write to the processed-alert ledger. When uncertain, pass the alert onward.
""".strip()


def build_monitor_agent(settings: Settings | None = None) -> Agent:
    """Create the narrow Monitor agent used by the supervisor."""
    resolved_settings = settings or Settings.from_environment()

    model = BedrockModel(
        model_id=resolved_settings.bedrock_model_id,
        region_name=resolved_settings.aws_region,
    )

    return Agent(
        name="monitor_agent",
        description="Retrieves all unseen FSA alert versions without judging relevance.",
        model=model,
        tools=[get_new_alerts],
        system_prompt=SYSTEM_PROMPT,
    )
