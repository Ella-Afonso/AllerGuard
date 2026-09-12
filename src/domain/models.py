"""Typed domain models shared across AllerGuard."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class AlertType(StrEnum):
    """Specific Food Standards Agency alert categories."""

    AA = "AA"
    PRIN = "PRIN"
    FAFA = "FAFA"


class ConfidenceTier(StrEnum):
    """How strongly an FSA alert relates to a business inventory."""

    NO_MATCH = "NO_MATCH"
    POSSIBLE = "POSSIBLE"
    LIKELY = "LIKELY"
    CONFIRMED = "CONFIRMED"


class Allergen(StrEnum):
    """The 14 regulated UK allergen categories."""

    CELERY = "celery"
    CEREALS_CONTAINING_GLUTEN = "cereals_containing_gluten"
    CRUSTACEANS = "crustaceans"
    EGGS = "eggs"
    FISH = "fish"
    LUPIN = "lupin"
    MILK = "milk"
    MOLLUSCS = "molluscs"
    MUSTARD = "mustard"
    TREE_NUTS = "tree_nuts"
    PEANUTS = "peanuts"
    SESAME = "sesame"
    SOYBEANS = "soybeans"
    SULPHUR_DIOXIDE_SULPHITES = "sulphur_dioxide_sulphites"


class MatchDimension(StrEnum):
    """Ways that an FSA alert can plausibly touch a business."""

    PRODUCT_BRAND = "PRODUCT_BRAND"
    INGREDIENT_SUPPLIER = "INGREDIENT_SUPPLIER"
    ALLERGEN = "ALLERGEN"
    CATEGORY = "CATEGORY"


class AlertBatch(BaseModel):
    """One batch-limiting detail from an FSA product detail."""

    product_name: str | None = None
    batch_code: str | None = None
    lot_number: str | None = None
    use_by_description: str | None = None
    best_before_description: str | None = None


class Alert(BaseModel):
    """A normalised Food Standards Agency food alert."""

    id: str
    id_uri: str
    type: AlertType
    title: str
    description: str | None
    created: date
    modified: datetime
    status: str
    alert_url: str | None
    allergens: list[str]
    products: list[str]

    reporting_business: str | None = None
    other_businesses: list[str] = Field(default_factory=list)
    allergen_notations: list[str] = Field(default_factory=list)
    batches: list[AlertBatch] = Field(default_factory=list)


class InventoryItem(BaseModel):
    """One product or ingredient the business sells or uses."""

    name: str
    kind: Literal["product", "ingredient"]
    ingredients: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)
    brand: str | None = None
    supplier: str | None = None
    categories: list[str] = Field(default_factory=list)
    batch_codes: list[str] = Field(default_factory=list)


class BusinessProfile(BaseModel):
    """The fictional demo business and its inventory."""

    business_id: str
    name: str
    inventory: list[InventoryItem]
    handled_allergens: list[str] = Field(default_factory=list)


class SeenAlertVersion(BaseModel):
    """One exact FSA alert version that has completed downstream processing."""

    alert_id: str
    modified: datetime


class MatchCandidate(BaseModel):
    """One plausible alert-to-inventory connection."""

    candidate_id: str = ""
    dimension: MatchDimension
    inventory_item_name: str | None
    alert_span: str
    fuzzy: bool = False
    evidence: str


class MatcherProposal(BaseModel):
    """Untrusted model judgement; authoritative evidence stays in application code."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    proposed_tier: ConfidenceTier
    reason: str = Field(min_length=1, max_length=600)
    evidence_refs: list[str]


class MatchResult(BaseModel):
    """The deterministic matching floor for one alert and business."""

    alert_id: str
    business_id: str
    tier: ConfidenceTier
    floor_tier: ConfidenceTier
    reason: str
    matched_items: list[str]
    dimensions: list[MatchDimension]
    candidates: list[MatchCandidate]


class ActionPack(BaseModel):
    """Owner-facing drafts; never a sent or approved action."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    pull: str = Field(min_length=1, max_length=800)
    staff_note: str = Field(min_length=1, max_length=800)
    customer_notice: str = Field(min_length=1, max_length=800)
    substitution: str = Field(min_length=1, max_length=800)


class ActionPackProposal(BaseModel):
    """Untrusted Drafter output; application code validates before queueing."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    pull: str = Field(min_length=1, max_length=800)
    staff_note: str = Field(min_length=1, max_length=800)
    customer_notice: str = Field(min_length=1, max_length=800)
    substitution: str = Field(min_length=1, max_length=800)


class DraftSource(StrEnum):
    """Whether the queued pack came from the model or a conservative fallback."""

    MODEL = "model"
    FALLBACK = "fallback"


class ActionDraftResult(BaseModel):
    """Accepted pack plus exact draft provenance; never a sent action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_pack: ActionPack
    draft_source: DraftSource
    drafter_model_id: str = Field(min_length=1)


class EscalationStatus(StrEnum):
    """Queue lifecycle. New queue rows are always pending."""

    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    DECLINED = "declined"


class GateDecision(StrEnum):
    """Whether an assessment needs a human decision; not proof of notification."""

    SILENT = "silent"
    ESCALATE = "escalate"


class AuditEvent(StrEnum):
    """Separate an assessed decision from an assessment that failed."""

    MATCH_DECISION = "match_decision"
    MATCH_ERROR = "match_error"
    ESCALATION_QUEUED = "escalation_queued"
    NOTIFICATION_SENT = "notification_sent"
    NOTIFICATION_FAILED = "notification_failed"
    NOTIFICATION_UNKNOWN = "notification_unknown"
    DECISION_RECORDED = "decision_recorded"


class AssessmentMode(StrEnum):
    """Keep injected test proposals distinct from real Bedrock assessments."""

    BEDROCK = "bedrock"
    INJECTED = "injected"


class Escalation(BaseModel):
    """One pending human decision: drafts stored, not executed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    escalation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    business_id: str = Field(min_length=1)
    assessment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    alert_id: str = Field(min_length=1)
    alert_modified: AwareDatetime
    alert_title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    status: EscalationStatus
    tier: ConfidenceTier | None
    floor_tier: ConfidenceTier | None
    reason: str = Field(min_length=1)
    action_pack: ActionPack
    draft_source: DraftSource
    policy_version: str = Field(min_length=1)
    draft_policy_version: str = Field(min_length=1)
    drafter_model_id: str = Field(min_length=1)
    queued_at: AwareDatetime

    @field_validator("alert_modified", "queued_at")
    @classmethod
    def normalise_time(cls, value: datetime) -> datetime:
        """Equivalent instants have one UTC representation."""
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def consistent_queue_row(self) -> Self:
        """Queue rows are pending, keyed by assessment, and never invent a tier."""
        if self.escalation_id != self.assessment_id:
            raise ValueError("escalation_id must equal assessment_id.")
        if self.status is not EscalationStatus.PENDING:
            raise ValueError("New escalations must be pending.")
        if self.tier is None:
            if self.draft_source is not DraftSource.FALLBACK:
                raise ValueError("An escalation without a tier must use the fallback pack.")
            if self.floor_tier is not None:
                raise ValueError("An escalation without a tier must not invent a floor.")
        elif self.floor_tier is None:
            raise ValueError("An assessed escalation needs both tiers.")
        else:
            ranks = {tier: rank for rank, tier in enumerate(ConfidenceTier)}
            if ranks[self.tier] < ranks[self.floor_tier]:
                raise ValueError("Escalation tier cannot be lower than its floor.")
        return self


class EscalationAppendResult(BaseModel):
    """The persisted first queue row, and whether this caller inserted it."""

    model_config = ConfigDict(frozen=True)
    escalation: Escalation
    created: bool


class OwnerDecision(StrEnum):
    """An explicit owner choice; never a model's escalation decision."""

    APPROVE = "approve"
    EDIT = "edit"
    DECLINE = "decline"


class DecisionRecord(BaseModel):
    """The first owner choice and both pack versions, without executing either."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    business_id: str = Field(min_length=1)
    escalation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: OwnerDecision
    decided_at: AwareDatetime
    original_action_pack: ActionPack
    edited_pack: ActionPack | None = None

    @field_validator("decided_at")
    @classmethod
    def normalise_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("original_action_pack", "edited_pack", mode="before")
    @classmethod
    def revalidate_pack(cls, value: object) -> ActionPack | None:
        if value is None:
            return None
        raw = value.model_dump() if isinstance(value, ActionPack) else value
        return ActionPack.model_validate(raw)

    @model_validator(mode="after")
    def consistent_choice(self) -> Self:
        if self.escalation_id != self.assessment_id:
            raise ValueError("Decision IDs must share one assessment.")
        if (self.decision is OwnerDecision.EDIT) != (self.edited_pack is not None):
            raise ValueError("Only EDIT requires an edited pack; APPROVE/DECLINE forbid one.")
        return self


class EscalationView(BaseModel):
    """Current status projected from immutable queue and decision facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    escalation: Escalation
    decision_record: DecisionRecord | None = None

    @model_validator(mode="after")
    def consistent_identity(self) -> Self:
        record = self.decision_record
        if record is not None:
            if (
                record.business_id != self.escalation.business_id
                or record.escalation_id != self.escalation.escalation_id
                or record.original_action_pack != self.escalation.action_pack
                or record.decided_at < self.escalation.queued_at
            ):
                raise ValueError("Decision does not match the original queue fact.")
        return self

    @property
    def effective_status(self) -> EscalationStatus:
        if self.decision_record is None:
            return EscalationStatus.PENDING
        return {
            OwnerDecision.APPROVE: EscalationStatus.APPROVED,
            OwnerDecision.EDIT: EscalationStatus.EDITED,
            OwnerDecision.DECLINE: EscalationStatus.DECLINED,
        }[self.decision_record.decision]


class NotificationOutcome(StrEnum):
    DISABLED = "disabled"
    ACCEPTED = "accepted"
    FAILED = "failed"
    UNKNOWN = "unknown"


class NotificationMode(StrEnum):
    LIVE = "live"
    SIMULATED = "simulated"
    DISABLED = "disabled"


class NotificationProvider(StrEnum):
    SES = "ses"
    SNS = "sns"
    LOG = "log"
    STUB = "stub"
    NONE = "none"


class NotificationReceipt(BaseModel):
    """Provider acceptance is distinct from delivery to an owner's inbox."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    business_id: str = Field(min_length=1)
    escalation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: NotificationOutcome
    provider: NotificationProvider
    mode: NotificationMode
    attempted_at: AwareDatetime | None = None
    message_id: str | None = Field(default=None, min_length=1, max_length=200)
    failure_type: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_]{0,79}$")

    @field_validator("attempted_at")
    @classmethod
    def normalise_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else value.astimezone(UTC)

    @model_validator(mode="after")
    def truthful_outcome(self) -> Self:
        if self.outcome is NotificationOutcome.DISABLED:
            if (
                self.mode is not NotificationMode.DISABLED
                or self.provider is not NotificationProvider.NONE
                or any(
                    v is not None for v in (self.attempted_at, self.message_id, self.failure_type)
                )
            ):
                raise ValueError("Disabled notification cannot claim an attempt.")
            return self
        if self.attempted_at is None or self.mode is NotificationMode.DISABLED:
            raise ValueError("Attempted notification requires time and execution mode.")
        allowed = (
            {NotificationProvider.STUB}
            if self.mode is NotificationMode.SIMULATED
            else {NotificationProvider.SES, NotificationProvider.SNS, NotificationProvider.LOG}
        )
        if self.provider not in allowed:
            raise ValueError("Notification provider contradicts its execution mode.")
        if self.outcome is NotificationOutcome.ACCEPTED:
            if (
                not self.message_id
                or self.failure_type
                or self.provider is NotificationProvider.LOG
            ):
                raise ValueError("Acceptance requires a provider message ID and no failure.")
        elif self.message_id is not None or not self.failure_type:
            raise ValueError(
                "Failed/unknown notification requires failure evidence and no message ID."
            )
        return self


class AuditEntry(BaseModel):
    """Immutable decision evidence. Error events have no invented match tier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: str
    assessment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    timestamp: AwareDatetime
    business_id: str = Field(min_length=1)
    alert_id: str = Field(min_length=1)
    alert_modified: AwareDatetime
    alert_title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    event: AuditEvent
    tier: ConfidenceTier | None
    floor_tier: ConfidenceTier | None
    decision: GateDecision
    reason: str = Field(min_length=1)
    error_type: str | None = None
    policy_version: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    mode: AssessmentMode
    candidate_ids: tuple[str, ...] = ()
    matched_items: tuple[str, ...] = ()
    draft_source: DraftSource | None = None
    notification: NotificationReceipt | None = None
    owner_decision: DecisionRecord | None = None

    @field_validator("timestamp", "alert_modified")
    @classmethod
    def normalise_time(cls, value: datetime) -> datetime:
        """Equivalent instants have one UTC representation."""
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def consistent_event(self) -> Self:
        """Reject contradictory records before they can enter the audit store."""
        if self.entry_id != f"{self.assessment_id}#{self.event.value}":
            raise ValueError("entry_id must identify the assessment and event.")
        notification_events = {
            AuditEvent.NOTIFICATION_SENT,
            AuditEvent.NOTIFICATION_FAILED,
            AuditEvent.NOTIFICATION_UNKNOWN,
        }
        if self.event not in notification_events and self.notification is not None:
            raise ValueError("Only notification events may retain notification evidence.")
        if self.event is not AuditEvent.DECISION_RECORDED and self.owner_decision is not None:
            raise ValueError("Only owner decision events may retain an owner choice.")
        if self.event is AuditEvent.MATCH_ERROR:
            if self.draft_source is not None:
                raise ValueError("A match event must not record a draft source.")
            if self.tier is not None or self.floor_tier is not None:
                raise ValueError("An assessment error must not invent a tier.")
            if self.decision is not GateDecision.ESCALATE or not self.error_type:
                raise ValueError("An assessment error must escalate with an error type.")
        elif self.event is AuditEvent.MATCH_DECISION:
            if self.draft_source is not None:
                raise ValueError("A match event must not record a draft source.")
            if self.tier is None or self.floor_tier is None or self.error_type is not None:
                raise ValueError("A match decision needs tiers and no error type.")
            expected = (
                GateDecision.SILENT
                if self.tier is ConfidenceTier.NO_MATCH
                else GateDecision.ESCALATE
            )
            if self.decision is not expected:
                raise ValueError("Audit decision contradicts its match tier.")
            ranks = {tier: rank for rank, tier in enumerate(ConfidenceTier)}
            if ranks[self.tier] < ranks[self.floor_tier]:
                raise ValueError("Audit tier cannot be lower than its floor.")
        elif self.event is AuditEvent.ESCALATION_QUEUED:
            if self.draft_source is None:
                raise ValueError("A queued escalation must record a draft source.")
            if self.decision is not GateDecision.ESCALATE:
                raise ValueError("A queued escalation must escalate.")
            if self.tier is None and self.floor_tier is None:
                if not self.error_type:
                    raise ValueError("An assessment error must escalate with an error type.")
            elif self.tier is None or self.floor_tier is None or self.error_type is not None:
                raise ValueError("A queued escalation cannot invent a partial or mixed tier.")
            else:
                if self.tier is ConfidenceTier.NO_MATCH:
                    raise ValueError("A queued escalation cannot record a NO_MATCH tier.")
                ranks = {tier: rank for rank, tier in enumerate(ConfidenceTier)}
                if ranks[self.tier] < ranks[self.floor_tier]:
                    raise ValueError("Audit tier cannot be lower than its floor.")
        else:
            # Validate the original escalation evidence without treating the new
            # event as a new assessment or changing its matcher error/tier.
            queued = self.model_dump(mode="python")
            queued.update(
                event=AuditEvent.ESCALATION_QUEUED,
                entry_id=f"{self.assessment_id}#escalation_queued",
                notification=None,
                owner_decision=None,
            )
            AuditEntry.model_validate(queued)
            if self.event in notification_events:
                receipt = self.notification
                expected_outcome = {
                    AuditEvent.NOTIFICATION_SENT: NotificationOutcome.ACCEPTED,
                    AuditEvent.NOTIFICATION_FAILED: NotificationOutcome.FAILED,
                    AuditEvent.NOTIFICATION_UNKNOWN: NotificationOutcome.UNKNOWN,
                }[self.event]
                if receipt is None or receipt.outcome is not expected_outcome:
                    raise ValueError("Notification event requires matching outcome evidence.")
                if (
                    receipt.business_id != self.business_id
                    or receipt.escalation_id != self.assessment_id
                    or receipt.attempted_at != self.timestamp
                ):
                    raise ValueError("Notification identity/time must match its audit event.")
            elif self.event is AuditEvent.DECISION_RECORDED:
                record = self.owner_decision
                if record is None or (
                    record.business_id != self.business_id
                    or record.assessment_id != self.assessment_id
                    or record.decided_at != self.timestamp
                ):
                    raise ValueError("Owner decision identity/time must match its audit event.")
        return self


class AuditAppendResult(BaseModel):
    """The persisted first record, and whether this caller inserted it."""

    model_config = ConfigDict(frozen=True)
    entry: AuditEntry
    created: bool


class DecisionAppendResult(BaseModel):
    """The stored first choice, with acknowledgement of its linked audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    record: DecisionRecord
    created: bool
    audit: AuditAppendResult

    @model_validator(mode="after")
    def consistent_record(self) -> Self:
        if self.audit.entry.event is not AuditEvent.DECISION_RECORDED:
            raise ValueError("Owner choice requires a decision-recorded audit event.")
        if self.audit.entry.owner_decision != self.record:
            raise ValueError("Stored choice and audit must agree.")
        return self


class ProcessedAlert(BaseModel):
    """The acknowledged result of match → gate → audit for one alert.

    The final match result is retained for a successful assessment; an
    assessment error has none and never invents one. The gate decision and the
    audit append result are retained so the caller can prove the decision was
    durably recorded (or that a prior identical record was reused). Escalated
    receipts also retain the pending queue row and its append-only queued event.
    """

    model_config = ConfigDict(frozen=True)
    match_result: MatchResult | None
    decision: GateDecision
    audit: AuditAppendResult
    escalation: EscalationAppendResult | None = None
    queue_audit: AuditAppendResult | None = None
    notification: NotificationReceipt | None = None

    @model_validator(mode="after")
    def consistent_with_audit(self) -> Self:
        """The retained parts must agree with the persisted record."""
        if self.decision is not self.audit.entry.decision:
            raise ValueError("decision must match the stored audit entry.")
        if self.match_result is not None and self.match_result.tier is not self.audit.entry.tier:
            raise ValueError("match result tier must match the stored audit entry.")
        if self.match_result is None and self.audit.entry.event is not AuditEvent.MATCH_ERROR:
            raise ValueError("only an assessment error has no match result.")
        if self.decision is GateDecision.SILENT:
            if (
                self.escalation is not None
                or self.queue_audit is not None
                or self.notification is not None
            ):
                raise ValueError("A silent path must not retain a queued escalation.")
        else:
            if self.escalation is None or self.queue_audit is None:
                raise ValueError("An escalated path must retain the queue row and queued audit.")
            if self.queue_audit.entry.event is not AuditEvent.ESCALATION_QUEUED:
                raise ValueError("queue_audit must be the escalation_queued event.")
            if self.queue_audit.entry.assessment_id != self.escalation.escalation.assessment_id:
                raise ValueError("Queued audit must share the escalation assessment identity.")
            if self.notification is not None and (
                self.notification.business_id != self.escalation.escalation.business_id
                or self.notification.escalation_id != self.escalation.escalation.escalation_id
            ):
                raise ValueError("Notification must identify the stored escalation.")
        return self

    @property
    def reused(self) -> bool:
        """True when a prior identical record was reused, not newly written."""
        return not self.audit.created
