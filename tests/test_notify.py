"""Provider-boundary tests: acceptance, fallback and honest uncertainty."""

from __future__ import annotations

from datetime import UTC, datetime

from botocore.exceptions import ClientError

from src.config import Settings
from src.domain.models import NotificationOutcome, NotificationProvider
from src.tools import notify
from tests.test_escalation_queue import row

NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def _settings(**changes: object) -> Settings:
    values: dict[str, object] = {
        "aws_region": "eu-west-2",
        "bedrock_model_id": "offline-test-model",
        "notification_mode": "ses",
        "ses_from_email": "owner@example.test",
        "owner_email": "owner@example.test",
    }
    values.update(changes)
    return Settings.model_validate(values)


class FakeClient:
    def __init__(self, response: dict[str, str] | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    def send_email(self, **kwargs: object) -> dict[str, str]:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response or {"MessageId": "ses-message"}

    def publish(self, **kwargs: object) -> dict[str, str]:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response or {"MessageId": "sns-message"}


def _rejection() -> ClientError:
    return ClientError(
        {"Error": {"Code": "MessageRejected", "Message": "synthetic rejection"}},
        "SendEmail",
    )


def test_disabled_does_not_create_or_call_a_provider(monkeypatch) -> None:
    settings = _settings(notification_mode="disabled", ses_from_email=None, owner_email=None)
    monkeypatch.setattr(
        notify.boto3,
        "client",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()),
    )
    receipt = notify.notify_owner(row(), settings, NOW)
    assert receipt.outcome is NotificationOutcome.DISABLED
    assert receipt.provider is NotificationProvider.NONE


def test_ses_message_contains_all_draft_evidence_and_no_recipient_override() -> None:
    client = FakeClient()
    receipt = notify.notify_owner(row(), _settings(), NOW, ses_client=client)
    assert receipt.outcome is NotificationOutcome.ACCEPTED
    assert receipt.provider is NotificationProvider.SES
    request = client.calls[0]
    assert request["Destination"] == {"ToAddresses": ["owner@example.test"]}
    subject = request["Message"]["Subject"]["Data"]
    body = request["Message"]["Body"]["Text"]["Data"]
    assert len(subject) <= 100
    for value in (
        "Pull:",
        "Staff note:",
        "Customer notice:",
        "Substitution:",
        "Draft source:",
        row().business_id,
    ):
        assert value in body
    assert "inbox" not in body.casefold() or "not" in body.casefold()


def test_definite_ses_rejection_uses_configured_sns_fallback() -> None:
    ses = FakeClient(error=_rejection())
    sns = FakeClient()
    receipt = notify.notify_owner(
        row(),
        _settings(sns_topic_arn="arn:aws:sns:eu-west-2:123456789012:owner-review"),
        NOW,
        ses_client=ses,
        sns_client=sns,
    )
    assert receipt.outcome is NotificationOutcome.ACCEPTED
    assert receipt.provider is NotificationProvider.SNS
    assert len(ses.calls) == len(sns.calls) == 1


def test_unfamiliar_ses_error_code_is_not_a_definite_rejection() -> None:
    ses = FakeClient(
        error=ClientError(
            {"Error": {"Code": "TotallyUnknownSesCode", "Message": "synthetic"}},
            "SendEmail",
        )
    )
    sns = FakeClient()
    receipt = notify.notify_owner(
        row(),
        _settings(sns_topic_arn="arn:aws:sns:eu-west-2:123456789012:owner-review"),
        NOW,
        ses_client=ses,
        sns_client=sns,
    )
    assert receipt.outcome is NotificationOutcome.UNKNOWN
    assert receipt.provider is NotificationProvider.SES
    assert receipt.failure_type == "TotallyUnknownSesCode"
    assert not sns.calls


def test_unknown_ses_failure_does_not_fallback() -> None:
    ses = FakeClient(error=TimeoutError("synthetic timeout"))
    sns = FakeClient()
    receipt = notify.notify_owner(
        row(),
        _settings(sns_topic_arn="arn:aws:sns:eu-west-2:123456789012:owner-review"),
        NOW,
        ses_client=ses,
        sns_client=sns,
    )
    assert receipt.outcome is NotificationOutcome.UNKNOWN
    assert receipt.provider is NotificationProvider.SES
    assert not sns.calls


def test_both_providers_definitely_fail_without_claiming_success() -> None:
    ses = FakeClient(error=_rejection())
    sns = FakeClient(error=_rejection())
    receipt = notify.notify_owner(
        row(),
        _settings(sns_topic_arn="arn:aws:sns:eu-west-2:123456789012:owner-review"),
        NOW,
        ses_client=ses,
        sns_client=sns,
    )
    assert receipt.outcome is NotificationOutcome.FAILED
    assert receipt.provider is NotificationProvider.SNS
    assert receipt.message_id is None


def test_log_mode_is_explicitly_not_delivered() -> None:
    receipt = notify.notify_owner(row(), _settings(notification_mode="log"), NOW)
    assert receipt.outcome is NotificationOutcome.FAILED
    assert receipt.provider is NotificationProvider.LOG
