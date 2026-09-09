"""Minimal Supervisor wiring for the Monitor-agent increment."""

from __future__ import annotations

from strands import Agent
from strands.models import BedrockModel

from src.agents.monitor import build_monitor_agent
from src.config import Settings

SYSTEM_PROMPT = """
You are AllerGuard's Supervisor.

For this Feature 10 increment, call monitor_agent once and return the unseen FSA
alert versions it reports. Do not decide relevance, escalation, owner messaging,
or audit outcomes.

Do not commit alert versions or advance the watermark. That is intentionally
deferred until Feature 20, when matching, the deterministic safety gate, and the
append-only audit trail exist.
""".strip()


def build_supervisor_agent(settings: Settings | None = None) -> Agent:
    """Create the thin supervisor with the Monitor agent exposed as a tool."""
    resolved_settings = settings or Settings.from_environment()
    monitor_agent = build_monitor_agent(resolved_settings)

    model = BedrockModel(
        model_id=resolved_settings.bedrock_model_id,
        region_name=resolved_settings.aws_region,
    )

    return Agent(
        name="supervisor_agent",
        description="Coordinates AllerGuard's monitoring pipeline.",
        model=model,
        tools=[
            monitor_agent.as_tool(
                name="monitor_agent",
                description="Retrieve every unseen FSA alert version for downstream work.",
            )
        ],
        system_prompt=SYSTEM_PROMPT,
    )
