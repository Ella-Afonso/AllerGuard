"""Thin Strands delegation over the trusted monitoring cycle."""

from __future__ import annotations

from strands import Agent
from strands.models import BedrockModel

from src.config import Settings
from src.domain.models import BusinessProfile
from src.tools.monitoring_cycle import build_cycle_tool

SYSTEM_PROMPT = """
You are AllerGuard's Supervisor. Delegate a monitoring request to monitoring_agent.
Do not assess relevance, draft advice, send notifications, record owner choices,
change the retrieved batch, or advance a watermark yourself.
The returned cycle evidence is authoritative. Blocked and uncertain outcomes
are not successes. Provider acceptance is not inbox receipt. Do not claim that
an owner approved anything or that stock or customer actions were executed.
""".strip()

MONITORING_PROMPT = """
Call run_cycle once for the configured business. Return its evidence JSON without
changing its counts or status. The deterministic runtime retrieves all unseen
versions and calls the existing Matcher and Action-Drafter pipeline. Do not
select alerts or invent a successful result if the tool fails or is not called.
""".strip()


def build_supervisor_agent(settings: Settings | None = None, *, business: BusinessProfile) -> Agent:
    """Build delegation; scheduled execution calls runtime directly.

    Agent narration is not an execution receipt. Consumers needing authoritative
    completion use the CycleReport returned by run_monitoring_cycle.
    """
    resolved_settings = settings or Settings.from_environment()

    model = BedrockModel(
        model_id=resolved_settings.bedrock_model_id,
        region_name=resolved_settings.aws_region,
    )

    monitoring_agent = Agent(
        name="monitoring_agent",
        description="Invokes the complete guarded cycle for the configured business.",
        model=model,
        tools=[build_cycle_tool(business, resolved_settings)],
        system_prompt=MONITORING_PROMPT,
    )

    return Agent(
        name="supervisor_agent",
        description="Coordinates AllerGuard's monitoring pipeline.",
        model=model,
        tools=[
            monitoring_agent.as_tool(
                name="monitoring_agent",
                description="Run the full guarded monitoring cycle and return recorded evidence.",
                delegate=True,
            )
        ],
        system_prompt=SYSTEM_PROMPT,
    )
