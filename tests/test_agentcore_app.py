"""Tests for AgentCore invocation input validation."""

from __future__ import annotations

import pytest

from src.runtime.agentcore_app import extract_prompt


def test_extract_prompt_returns_trimmed_string() -> None:
    """A valid prompt is returned without surrounding whitespace."""
    assert extract_prompt({"prompt": "  Run the readiness check.  "}) == (
        "Run the readiness check."
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"prompt": ""},
        {"prompt": "   "},
        {"prompt": 123},
        {"prompt": ["not", "a", "string"]},
    ],
)
def test_extract_prompt_rejects_invalid_payloads(payload: dict[str, object]) -> None:
    """Invalid AgentCore payloads are rejected before reaching the agent."""
    with pytest.raises(ValueError, match="non-empty string"):
        extract_prompt(payload)
