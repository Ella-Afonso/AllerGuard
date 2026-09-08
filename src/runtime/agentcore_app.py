"""Amazon Bedrock AgentCore Runtime entry point for the AllerGuard Hello agent."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext

from src.agents.hello import build_hello_agent

logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()


def extract_prompt(payload: Mapping[str, object]) -> str:
    """Validate and return the prompt supplied to the AgentCore runtime."""
    prompt = payload.get("prompt")

    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("'prompt' must be a non-empty string")

    return prompt.strip()


@app.entrypoint
def invoke_hello_agent(
    payload: Mapping[str, object],
    context: RequestContext,
) -> dict[str, str]:
    """Run the existing Hello agent for one validated AgentCore request."""
    try:
        prompt = extract_prompt(payload)
    except ValueError as error:
        logger.warning("Rejected invalid AgentCore invocation payload")
        return {"error": str(error)}

    logger.info("Received validated AgentCore Hello-agent invocation")
    agent = build_hello_agent()
    result = agent(prompt)
    response_text = str(result).strip()

    logger.info("Completed AgentCore Hello-agent invocation")
    return {"result": response_text}


if __name__ == "__main__":
    app.run()
