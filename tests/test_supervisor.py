"""Supervisor exposes only the bound monitoring capability."""

from src.agents.supervisor import build_supervisor_agent
from src.config import Settings
from src.domain.demo_cafe import build_demo_profile


def test_supervisor_has_one_delegated_monitoring_tool() -> None:
    settings = Settings(aws_region="eu-west-2", bedrock_model_id="offline-test-model")
    agent = build_supervisor_agent(settings, business=build_demo_profile())
    assert agent.tool_names == ["monitoring_agent"]
    assert "watermark" in agent.system_prompt.lower()
    assert "owner" in agent.system_prompt.lower()


def test_cycle_capability_has_no_user_inputs() -> None:
    settings = Settings(aws_region="eu-west-2", bedrock_model_id="offline-test-model")
    agent = build_supervisor_agent(settings, business=build_demo_profile())
    delegated = agent.tool_registry.registry["monitoring_agent"]
    tool = delegated._agent.tool_registry.registry["run_cycle"]
    assert tool.tool_name == "run_cycle"
    assert tool.tool_spec["inputSchema"]["json"]["properties"] == {}
