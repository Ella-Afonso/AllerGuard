"""Tool boundary for invoking an AllerGuard AgentCore Runtime."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

import boto3

logger = logging.getLogger(__name__)


def invoke_agentcore_runtime(
    *,
    prompt: str,
    runtime_arn: str,
    region: str,
) -> str:
    """Invoke one AgentCore Runtime session with a validated text prompt."""
    client = boto3.client("bedrock-agentcore", region_name=region)
    session_id = f"eventbridge-{uuid4().hex}"

    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=session_id,
        payload=json.dumps({"prompt": prompt}).encode("utf-8"),
        qualifier="DEFAULT",
    )

    response_text = response["response"].read().decode("utf-8")

    logger.info("AgentCore Runtime invocation completed; session_id=%s", session_id)
    return response_text
