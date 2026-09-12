"""Pure, validated evidence for a serial monitoring cycle."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field, model_validator


class CycleStatus(StrEnum):
    EMPTY = "empty"
    COMMITTED = "committed"
    BLOCKED = "blocked"
    COMMIT_UNKNOWN = "commit_outcome_unknown"


class AlertOutcome(StrEnum):
    SILENT = "silent"
    ESCALATED = "escalated"
    HANDLED_ERROR = "handled_matcher_error"
    BLOCKED = "blocked"


class CycleAlertResult(BaseModel):
    """One retrieved version, including any failure that prevented completion."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    alert_id: str = Field(min_length=1)
    modified: AwareDatetime
    outcome: AlertOutcome
    assessment_id: str | None = None
    error_type: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def evidence_matches_outcome(self) -> Self:
        if self.outcome is AlertOutcome.BLOCKED and self.error_type is None:
            raise ValueError("Blocked alert requires a diagnostic classification.")
        if self.outcome is not AlertOutcome.BLOCKED and not self.assessment_id:
            raise ValueError("Completed alert requires a persisted assessment identity.")
        return self


class CycleReport(BaseModel):
    """Counts derive from immutable per-alert evidence, never model narration."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    cycle_id: str = Field(min_length=1)
    business_id: str = Field(min_length=1)
    started_at: AwareDatetime
    finished_at: AwareDatetime
    status: CycleStatus
    alerts: tuple[CycleAlertResult, ...] = ()
    watermark_before: AwareDatetime | None = None
    watermark_after: AwareDatetime | None = None
    error_type: str | None = Field(default=None, min_length=1, max_length=80)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def retrieved(self) -> int:
        return len(self.alerts)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def silent(self) -> int:
        return sum(row.outcome is AlertOutcome.SILENT for row in self.alerts)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def escalated(self) -> int:
        return sum(
            row.outcome in (AlertOutcome.ESCALATED, AlertOutcome.HANDLED_ERROR)
            for row in self.alerts
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def handled_errors(self) -> int:
        return sum(row.outcome is AlertOutcome.HANDLED_ERROR for row in self.alerts)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def blocked(self) -> int:
        return sum(row.outcome is AlertOutcome.BLOCKED for row in self.alerts)

    @model_validator(mode="after")
    def consistent_report(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("Cycle finish must not precede its start.")
        versions = {(row.alert_id, row.modified) for row in self.alerts}
        if len(versions) != self.retrieved:
            raise ValueError("A retrieved version must appear only once.")
        if self.status is CycleStatus.EMPTY:
            if self.alerts or self.error_type or self.watermark_before != self.watermark_after:
                raise ValueError("An empty cycle cannot process alerts or change the watermark.")
        elif self.status is CycleStatus.COMMITTED:
            if not self.alerts or self.blocked or self.error_type or self.watermark_after is None:
                raise ValueError("Committed requires a complete nonempty batch and read-back.")
            if self.watermark_after < max(row.modified for row in self.alerts):
                raise ValueError("Committed watermark must cover the complete batch.")
        elif self.status is CycleStatus.COMMIT_UNKNOWN:
            if not self.alerts or self.blocked or not self.error_type:
                raise ValueError("Uncertain commit requires a processed batch and diagnostic.")
        elif not self.blocked and not self.error_type:
            raise ValueError("Blocked cycle requires a failure classification.")
        return self
