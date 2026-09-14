"""Human-readable labels for evidence already stored elsewhere.

This module never mutates records. Short references are display-only.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from src.domain.diary import DiaryEvent
from src.domain.models import (
    AssessmentMode,
    AuditEvent,
    ConfidenceTier,
    DraftSource,
    GateDecision,
    OwnerDecision,
)

BUSINESS_TIMEZONE = ZoneInfo("Europe/London")
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_EVENT_LABELS: dict[str, str] = {
    AuditEvent.MATCH_DECISION.value: "Assessment recorded",
    AuditEvent.MATCH_ERROR.value: "Assessment failed",
    AuditEvent.ESCALATION_QUEUED.value: "Escalation queued",
    AuditEvent.NOTIFICATION_SENT.value: "Notification recorded",
    AuditEvent.NOTIFICATION_FAILED.value: "Notification failed",
    AuditEvent.NOTIFICATION_UNKNOWN.value: "Notification outcome unknown",
    AuditEvent.DECISION_RECORDED.value: "Owner decision recorded",
    DiaryEvent.FILED.value: "Daily diary filed",
    DiaryEvent.CONFIRMED.value: "Diary confirmation recorded",
    DiaryEvent.ERROR.value: "Diary error recorded",
}


def format_display_time(value: datetime) -> str:
    """Render an aware timestamp in Europe/London without seconds or ISO noise."""
    if value.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware.")
    local = value.astimezone(BUSINESS_TIMEZONE)
    zone = local.tzname() or "Europe/London"
    return f"{local.day} {_MONTHS[local.month - 1]} {local.year}, {local:%H:%M} {zone}"


def format_display_date(value: date) -> str:
    """Render a calendar date in the same month-name style as display times."""
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def event_display_label(event: StrEnum | str) -> str:
    """Map a stored event enum to a plain English label."""
    key = event.value if isinstance(event, StrEnum) else event
    return _EVENT_LABELS.get(key, key.replace("_", " ").capitalize())


def short_evidence_reference(entry_id: str) -> str:
    """Shorten a stored identity for labels only; the stored value is unchanged."""
    identity, _, _suffix = entry_id.partition("#")
    if len(identity) < 16:
        return identity
    return f"{identity[:8]}…{identity[-5:]}"


def assessment_result_label(tier: ConfidenceTier | None) -> str:
    if tier is None:
        return "Assessment incomplete"
    return {
        ConfidenceTier.NO_MATCH: "No recorded match",
        ConfidenceTier.POSSIBLE: "Possible match",
        ConfidenceTier.LIKELY: "Likely match",
        ConfidenceTier.CONFIRMED: "Confirmed match",
    }[tier]


def gate_result_label(decision: GateDecision) -> str:
    if decision is GateDecision.SILENT:
        return "Handled quietly"
    return "Owner review required"


def assessment_source_label(mode: AssessmentMode, draft_source: DraftSource | None = None) -> str:
    if mode is AssessmentMode.INJECTED:
        return "Injected replay proposal"
    if draft_source is DraftSource.FALLBACK:
        return "Conservative fallback draft"
    if draft_source is DraftSource.MODEL:
        return "Model draft"
    return "Bedrock assessment"


def owner_choice_label(choice: OwnerDecision | str) -> str:
    key = choice.value if isinstance(choice, OwnerDecision) else choice
    return {"approve": "Approve", "edit": "Edit", "decline": "Decline"}.get(key, key)
