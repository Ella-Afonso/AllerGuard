"""Typed domain models shared across AllerGuard."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
