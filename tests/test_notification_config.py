"""Notification opt-in is independent from feed source and model test settings."""

import pytest
from pydantic import ValidationError

from src.config import Settings

TOPIC = "arn:aws:sns:eu-west-2:123456789012:synthetic-notifications"


@pytest.fixture(autouse=True)
def clear_notification_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ALLERGUARD_NOTIFICATION_MODE",
        "ALLERGUARD_OWNER_EMAIL",
        "ALLERGUARD_SES_FROM_EMAIL",
        "ALLERGUARD_SNS_TOPIC_ARN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_REGION", "eu-west-2")


def test_default_needs_no_provider_configuration() -> None:
    assert Settings.from_environment().notification_mode == "disabled"
    assert Settings(aws_region="eu-west-2", bedrock_model_id="offline").owner_email is None


@pytest.mark.parametrize("mode", ["live", "email", "", "SES"])
def test_invalid_mode_is_rejected(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLERGUARD_NOTIFICATION_MODE", mode)
    with pytest.raises(ValidationError):
        Settings.from_environment()


@pytest.mark.parametrize("mode", ["ses", "sns"])
def test_live_mode_needs_its_configuration(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLERGUARD_NOTIFICATION_MODE", mode)
    with pytest.raises(ValidationError):
        Settings.from_environment()


@pytest.mark.parametrize("mode", ["ses", "sns", "log"])
def test_configured_modes(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLERGUARD_NOTIFICATION_MODE", mode)
    monkeypatch.setenv("ALLERGUARD_SES_FROM_EMAIL", "sender@example.com")
    monkeypatch.setenv("ALLERGUARD_OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("ALLERGUARD_SNS_TOPIC_ARN", TOPIC)
    settings = Settings.from_environment()
    assert settings.notification_mode == mode
    assert settings.sns_topic_arn == TOPIC
    assert "owner@example.com" not in repr(settings)


@pytest.mark.parametrize(
    "address", ["a@example.com\nBcc: b@example.com", "a@example.com,b@example.com", "", "plain"]
)
def test_reject_header_or_recipient_injection(
    address: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLERGUARD_OWNER_EMAIL", address)
    with pytest.raises(ValidationError):
        Settings.from_environment()


@pytest.mark.parametrize(
    "topic", [TOPIC + ".fifo", TOPIC.replace("eu-west-2", "us-east-1"), "not-an-arn"]
)
def test_email_topic_must_be_standard_and_same_region(
    topic: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLERGUARD_SNS_TOPIC_ARN", topic)
    with pytest.raises(ValidationError):
        Settings.from_environment()


def test_feed_or_bedrock_optin_does_not_enable_notifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLERGUARD_FSA_MODE", "live")
    monkeypatch.setenv("ALLERGUARD_LIVE_BEDROCK", "1")
    settings = Settings.from_environment()
    assert settings.fsa_mode == "live"
    assert settings.notification_mode == "disabled"
