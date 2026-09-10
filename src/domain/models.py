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


class GateDecision(StrEnum):
    """Whether an assessment needs a human decision; not proof of notification."""

    SILENT = "silent"
    ESCALATE = "escalate"


class AuditEvent(StrEnum):
    """Separate an assessed decision from an assessment that failed."""

    MATCH_DECISION = "match_decision"
    MATCH_ERROR = "match_error"


class AssessmentMode(StrEnum):
    """Keep injected test proposals distinct from real Bedrock assessments."""

    BEDROCK = "bedrock"
    INJECTED = "injected"


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
        if self.event is AuditEvent.MATCH_ERROR:
            if self.tier is not None or self.floor_tier is not None:
                raise ValueError("An assessment error must not invent a tier.")
            if self.decision is not GateDecision.ESCALATE or not self.error_type:
                raise ValueError("An assessment error must escalate with an error type.")
        else:
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
        return self


class AuditAppendResult(BaseModel):
    """The persisted first record, and whether this caller inserted it."""

    model_config = ConfigDict(frozen=True)
    entry: AuditEntry
    created: bool


class ProcessedAlert(BaseModel):
    """The acknowledged result of match → gate → audit for one alert.

    The final match result is retained for a successful assessment; an
    assessment error has none and never invents one. The gate decision and the
    audit append result are retained so the caller can prove the decision was
    durably recorded (or that a prior identical record was reused).
    """

    model_config = ConfigDict(frozen=True)
    match_result: MatchResult | None
    decision: GateDecision
    audit: AuditAppendResult

    @model_validator(mode="after")
    def consistent_with_audit(self) -> Self:
        """The retained parts must agree with the persisted record."""
        if self.decision is not self.audit.entry.decision:
            raise ValueError("decision must match the stored audit entry.")
        if self.match_result is not None and self.match_result.tier is not self.audit.entry.tier:
            raise ValueError("match result tier must match the stored audit entry.")
        if self.match_result is None and self.audit.entry.event is not AuditEvent.MATCH_ERROR:
            raise ValueError("only an assessment error has no match result.")
        return self

    @property
    def reused(self) -> bool:
        """True when a prior identical record was reused, not newly written."""
        return not self.audit.created
