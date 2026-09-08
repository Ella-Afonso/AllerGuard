"""Tests for EventBridge scheduled invocation input."""

from __future__ import annotations

from src.runtime.scheduled_invoke import DEFAULT_SCHEDULED_PROMPT, get_scheduled_prompt


def test_get_scheduled_prompt_uses_safe_default() -> None:
    """The schedule uses the fixed safe prompt when no override is supplied."""
    assert get_scheduled_prompt({}) == DEFAULT_SCHEDULED_PROMPT


def test_get_scheduled_prompt_accepts_non_empty_override() -> None:
    """A valid supplied prompt is trimmed and used."""
    assert get_scheduled_prompt({"prompt": "  Run the demo check.  "}) == ("Run the demo check.")


def test_get_scheduled_prompt_rejects_empty_override() -> None:
    """An empty prompt falls back to the safe default."""
    assert get_scheduled_prompt({"prompt": "   "}) == DEFAULT_SCHEDULED_PROMPT
