"""Owner-notification delivery boundary.

This module is deliberately the only notification boundary that creates SES/SNS clients.
It reports provider acceptance separately from inbox receipt and never executes
an action pack or records an owner decision.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from src.config import Settings
from src.domain.models import (
    Escalation,
    NotificationMode,
    NotificationOutcome,
    NotificationProvider,
    NotificationReceipt,
)

logger = logging.getLogger(__name__)

_SUBJECT_LIMIT = 100
_DEFINITE_SES_REJECTIONS = frozenset(
    {
        "ConfigurationSetDoesNotExist",
        "InvalidParameterValue",
        "MailFromDomainNotVerifiedException",
        "MessageRejected",
        "SendingPausedException",
    }
)


def _subject(escalation: Escalation) -> str:
    """Create a bounded subject from stored alert text."""
    title = " ".join(escalation.alert_title.split())
    value = f"AllerGuard review required: {title}"
    return value[:_SUBJECT_LIMIT]


def _message(escalation: Escalation) -> str:
    """Render every stored draft field with an explicit no-execution warning."""
    pack = escalation.action_pack
    tier = escalation.tier.value if escalation.tier is not None else "UNASSESSED"
    floor = escalation.floor_tier.value if escalation.floor_tier is not None else "UNASSESSED"
    return "\n".join(
        (
            "AllerGuard owner review required.",
            "This is an owner notification about a stored draft; no customer or stock "
            "action was executed.",
            f"Business: {escalation.business_id}",
            f"Escalation ID: {escalation.escalation_id}",
            f"Alert: {escalation.alert_title}",
            f"Tier: {tier} (floor: {floor})",
            f"Reason: {escalation.reason}",
            f"Draft source: {escalation.draft_source.value}",
            f"Drafter model: {escalation.drafter_model_id}",
            "",
            "DRAFT ACTION PACK — NOT EXECUTED:",
            f"Pull: {pack.pull}",
            f"Staff note: {pack.staff_note}",
            f"Customer notice: {pack.customer_notice}",
            f"Substitution: {pack.substitution}",
            "",
            "Recording an approval is a human decision record; it does not send this "
            "draft to customers.",
        )
    )


def _failure_type(error: BaseException) -> tuple[str, bool]:
    """Return a safe classification and whether the provider definitely rejected."""
    if isinstance(error, ClientError):
        code = str(error.response.get("Error", {}).get("Code", "ClientError"))
        return (code[:80] or "ClientError", code in _DEFINITE_SES_REJECTIONS)
    if isinstance(error, (TimeoutError, BotoCoreError)):
        return (type(error).__name__[:80], False)
    return (type(error).__name__[:80] or "ProviderError", False)


def _receipt(
    escalation: Escalation,
    *,
    outcome: NotificationOutcome,
    provider: NotificationProvider,
    attempted_at: datetime,
    message_id: str | None = None,
    failure_type: str | None = None,
) -> NotificationReceipt:
    return NotificationReceipt(
        business_id=escalation.business_id,
        escalation_id=escalation.escalation_id,
        outcome=outcome,
        provider=provider,
        mode=NotificationMode.LIVE,
        attempted_at=attempted_at,
        message_id=message_id,
        failure_type=failure_type,
    )


def _send_ses(escalation: Escalation, settings: Settings, client: Any) -> str:
    """Send through SES and require its acceptance identifier."""
    response = client.send_email(
        Source=settings.ses_from_email,
        Destination={"ToAddresses": [settings.owner_email]},
        Message={
            "Subject": {"Data": _subject(escalation), "Charset": "UTF-8"},
            "Body": {"Text": {"Data": _message(escalation), "Charset": "UTF-8"}},
        },
    )
    message_id = response.get("MessageId") if isinstance(response, dict) else None
    if not isinstance(message_id, str) or not message_id.strip():
        raise RuntimeError("ProviderResponseMissingMessageId")
    return message_id


def _send_sns(escalation: Escalation, settings: Settings, client: Any) -> str:
    """Publish an internal owner-review message to the configured topic."""
    response = client.publish(
        TopicArn=settings.sns_topic_arn,
        Subject=_subject(escalation),
        Message=_message(escalation),
    )
    message_id = response.get("MessageId") if isinstance(response, dict) else None
    if not isinstance(message_id, str) or not message_id.strip():
        raise RuntimeError("ProviderResponseMissingMessageId")
    return message_id


def notify_owner(
    escalation: Escalation,
    settings: Settings,
    attempted_at: datetime,
    *,
    ses_client: Any | None = None,
    sns_client: Any | None = None,
) -> NotificationReceipt:
    """Attempt one explicit owner notification and return truthful evidence.

    SES is primary when configured. SNS is used only after a definite SES
    rejection and only when a topic is configured. Unknown transport outcomes
    never trigger an automatic fallback or retry.
    """
    if attempted_at.tzinfo is None or attempted_at.utcoffset() is None:
        raise ValueError("attempted_at must include a timezone.")
    if settings.notification_mode == "disabled":
        return NotificationReceipt(
            business_id=escalation.business_id,
            escalation_id=escalation.escalation_id,
            outcome=NotificationOutcome.DISABLED,
            provider=NotificationProvider.NONE,
            mode=NotificationMode.DISABLED,
        )
    if settings.notification_mode == "log":
        logger.info(
            "owner_notification_log_only business=%s escalation=%s",
            escalation.business_id,
            escalation.escalation_id,
        )
        return _receipt(
            escalation,
            outcome=NotificationOutcome.FAILED,
            provider=NotificationProvider.LOG,
            attempted_at=attempted_at,
            failure_type="LogOnlyNotDelivered",
        )

    if settings.notification_mode == "sns":
        client = sns_client or boto3.client("sns", region_name=settings.aws_region)
        try:
            message_id = _send_sns(escalation, settings, client)
        except Exception as error:  # provider boundary: classify, don't claim success
            failure_type, definite = _failure_type(error)
            return _receipt(
                escalation,
                outcome=NotificationOutcome.FAILED if definite else NotificationOutcome.UNKNOWN,
                provider=NotificationProvider.SNS,
                attempted_at=attempted_at,
                failure_type=failure_type,
            )
        return _receipt(
            escalation,
            outcome=NotificationOutcome.ACCEPTED,
            provider=NotificationProvider.SNS,
            attempted_at=attempted_at,
            message_id=message_id,
        )

    client = ses_client or boto3.client("ses", region_name=settings.aws_region)
    try:
        message_id = _send_ses(escalation, settings, client)
    except Exception as error:  # provider boundary: classify, don't claim success
        failure_type, definite = _failure_type(error)
        if definite and settings.sns_topic_arn:
            fallback = sns_client or boto3.client("sns", region_name=settings.aws_region)
            try:
                fallback_id = _send_sns(escalation, settings, fallback)
            except Exception as fallback_error:
                fallback_type, fallback_definite = _failure_type(fallback_error)
                return _receipt(
                    escalation,
                    outcome=NotificationOutcome.FAILED
                    if fallback_definite
                    else NotificationOutcome.UNKNOWN,
                    provider=NotificationProvider.SNS,
                    attempted_at=attempted_at,
                    failure_type=fallback_type,
                )
            return _receipt(
                escalation,
                outcome=NotificationOutcome.ACCEPTED,
                provider=NotificationProvider.SNS,
                attempted_at=attempted_at,
                message_id=fallback_id,
            )
        return _receipt(
            escalation,
            outcome=NotificationOutcome.FAILED if definite else NotificationOutcome.UNKNOWN,
            provider=NotificationProvider.SES,
            attempted_at=attempted_at,
            failure_type=failure_type,
        )
    return _receipt(
        escalation,
        outcome=NotificationOutcome.ACCEPTED,
        provider=NotificationProvider.SES,
        attempted_at=attempted_at,
        message_id=message_id,
    )
