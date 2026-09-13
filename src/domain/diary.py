"""Daily record facts and projections; no inference of physical work."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal, Self
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from src.domain.models import ActionPack, AuditEntry, AuditEvent, DraftSource, OwnerDecision

BUSINESS_TIMEZONE: Literal["Europe/London"] = "Europe/London"


class DailyStatus(StrEnum):
    UNCONFIRMED = "unconfirmed"
    CONFIRMED = "confirmed"
    EXCEPTION = "exception"


class DiaryEvent(StrEnum):
    FILED = "diary_filed"
    CONFIRMED = "diary_confirmed"
    ERROR = "diary_error"


class DailyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RecallDiaryLink(DailyModel):
    event_id: str = Field(min_length=1)
    assessment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    alert_id: str = Field(min_length=1)
    alert_title: str = Field(min_length=1)
    evidence_at: AwareDatetime
    state: Literal["pending", "approve", "edit", "decline"]
    original_action_pack: ActionPack | None = None
    edited_pack: ActionPack | None = None


class DiaryEntry(DailyModel):
    entry_date: date
    business_id: str = Field(min_length=1)
    business_timezone: Literal["Europe/London"] = BUSINESS_TIMEZONE
    filed_at: AwareDatetime
    evidence_cutoff: AwareDatetime
    opening_status: Literal[DailyStatus.UNCONFIRMED] = DailyStatus.UNCONFIRMED
    closing_status: Literal[DailyStatus.UNCONFIRMED] = DailyStatus.UNCONFIRMED
    recall_actions: tuple[RecallDiaryLink, ...] = ()
    exceptions: tuple[str, ...] = ("Opening and closing await owner confirmation.",)
    notes: str = Field(default="", max_length=2000)
    summary: str = Field(min_length=1, max_length=1000)
    summary_source: DraftSource = DraftSource.FALLBACK
    summary_model_id: str = Field(default="deterministic", min_length=1)

    @model_validator(mode="after")
    def valid_time(self) -> Self:
        if self.evidence_cutoff > self.filed_at:
            raise ValueError("Evidence cutoff cannot follow filing.")
        if self.entry_date > business_date(self.filed_at):
            raise ValueError("Cannot file a future business date.")
        if any(link.evidence_at > self.evidence_cutoff for link in self.recall_actions):
            raise ValueError("Diary links cannot follow the evidence cutoff.")
        if len({link.event_id for link in self.recall_actions}) != len(self.recall_actions):
            raise ValueError("Duplicate diary evidence.")
        return self


class DiaryConfirmation(DailyModel):
    opening_status: DailyStatus
    closing_status: DailyStatus
    note: str = Field(default="", max_length=2000)
    mode: Literal["owner", "simulated"] = "owner"

    @model_validator(mode="after")
    def explicit_answers(self) -> Self:
        statuses = (self.opening_status, self.closing_status)
        if DailyStatus.UNCONFIRMED in statuses:
            raise ValueError("Both opening and closing require an explicit answer.")
        if DailyStatus.EXCEPTION in statuses and not self.note:
            raise ValueError("An exception requires an explanation.")
        return self


class DiaryRecord(DailyModel):
    entry_id: str
    business_id: str = Field(min_length=1)
    entry_date: date
    timestamp: AwareDatetime
    event: DiaryEvent
    diary: DiaryEntry | None = None
    confirmation: DiaryConfirmation | None = None
    error_type: str | None = None

    @model_validator(mode="after")
    def consistent_record(self) -> Self:
        identity = diary_id(self.entry_date)
        if self.event is DiaryEvent.FILED:
            if self.entry_id != identity or self.diary is None:
                raise ValueError("Filing requires its date identity and diary.")
            if self.confirmation is not None or self.error_type is not None:
                raise ValueError("Filing cannot carry confirmation or error data.")
            if (self.diary.business_id, self.diary.entry_date, self.diary.filed_at) != (
                self.business_id,
                self.entry_date,
                self.timestamp,
            ):
                raise ValueError("Diary identity or filing time does not match its envelope.")
        elif self.event is DiaryEvent.CONFIRMED:
            if self.entry_id != identity + "#confirmed" or self.confirmation is None:
                raise ValueError("Confirmation requires its date identity and answers.")
            if self.diary is not None or self.error_type is not None:
                raise ValueError("Confirmation cannot replace a diary or contain error data.")
        elif (
            not self.entry_id.startswith(identity + "#error#")
            or not self.error_type
            or self.diary is not None
            or self.confirmation is not None
        ):
            raise ValueError("Error records require an error identity and type only.")
        return self


class DiaryAppendResult(DailyModel):
    record: DiaryRecord
    created: bool


class DiaryView(DailyModel):
    filed: DiaryRecord
    confirmation: DiaryRecord | None = None
    as_of: AwareDatetime
    current_recall_actions: tuple[RecallDiaryLink, ...]
    additional_links: tuple[RecallDiaryLink, ...]


def diary_id(entry_date: date) -> str:
    return f"diary#{entry_date.isoformat()}"


def business_date(instant: datetime) -> date:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("An aware timestamp is required.")
    return instant.astimezone(ZoneInfo(BUSINESS_TIMEZONE)).date()


def recall_links(
    entry_date: date, business_id: str, entries: Sequence[AuditEntry], *, as_of: datetime
) -> tuple[RecallDiaryLink, ...]:
    """Today's owner decisions plus still-pending queues, including older unresolved queues."""
    business_date(as_of)
    rows = [
        row
        for row in entries
        if row.business_id == business_id
        and row.timestamp <= as_of
        and business_date(row.timestamp) <= entry_date
    ]
    decided = {
        row.assessment_id
        for row in rows
        if row.event is AuditEvent.DECISION_RECORDED
        and row.owner_decision is not None
        and row.owner_decision.decided_at <= as_of
    }
    links: dict[str, RecallDiaryLink] = {}
    for row in rows:
        decision = row.owner_decision
        is_decision = row.event is AuditEvent.DECISION_RECORDED and decision is not None
        evidence_at = decision.decided_at if is_decision and decision else row.timestamp
        if evidence_at > as_of:
            continue
        if is_decision:
            if business_date(evidence_at) != entry_date:
                continue
        elif (
            row.event is not AuditEvent.ESCALATION_QUEUED
            or row.assessment_id in decided
            or business_date(evidence_at) > entry_date
        ):
            continue
        state: Literal["pending", "approve", "edit", "decline"] = "pending"
        if is_decision and decision:
            states: dict[OwnerDecision, Literal["approve", "edit", "decline"]] = {
                OwnerDecision.APPROVE: "approve",
                OwnerDecision.EDIT: "edit",
                OwnerDecision.DECLINE: "decline",
            }
            state = states[decision.decision]
        links[row.entry_id] = RecallDiaryLink(
            event_id=row.entry_id,
            assessment_id=row.assessment_id,
            alert_id=row.alert_id,
            alert_title=row.alert_title,
            evidence_at=evidence_at,
            state=state,
            original_action_pack=decision.original_action_pack if decision else None,
            edited_pack=decision.edited_pack if decision else None,
        )
    return tuple(sorted(links.values(), key=lambda link: (link.evidence_at, link.event_id)))


def build_diary_entry(
    entry_date: date, business_id: str, entries: Sequence[AuditEntry], *, now: datetime
) -> DiaryEntry:
    links = recall_links(entry_date, business_id, entries, as_of=now)
    choices = sum(link.state != "pending" for link in links)
    pending = len(links) - choices
    return DiaryEntry(
        entry_date=entry_date,
        business_id=business_id,
        filed_at=now.astimezone(UTC),
        evidence_cutoff=now.astimezone(UTC),
        recall_actions=links,
        summary=f"{choices} owner choices recorded; {pending} recalls awaiting review. "
        "Opening and closing await owner confirmation. No physical action is inferred.",
    )


def build_diary_view(
    filed: DiaryRecord,
    confirmation: DiaryRecord | None,
    entries: Sequence[AuditEntry],
    *,
    as_of: datetime,
) -> DiaryView:
    if filed.diary is None or as_of < filed.timestamp:
        raise ValueError("A filed diary at or before the view time is required.")
    if confirmation is not None and (
        confirmation.event is not DiaryEvent.CONFIRMED
        or confirmation.business_id != filed.business_id
        or confirmation.entry_date != filed.entry_date
        or not filed.timestamp <= confirmation.timestamp <= as_of
    ):
        raise ValueError("Confirmation does not belong to this diary view.")
    links = recall_links(filed.entry_date, filed.business_id, entries, as_of=as_of)
    original = {link.event_id for link in filed.diary.recall_actions}
    return DiaryView(
        filed=filed,
        confirmation=confirmation,
        as_of=as_of,
        current_recall_actions=links,
        additional_links=tuple(link for link in links if link.event_id not in original),
    )
