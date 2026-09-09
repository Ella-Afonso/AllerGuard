"""Typed domain models shared across AllerGuard."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AlertType(StrEnum):
    """Specific Food Standards Agency alert categories."""

    AA = "AA"
    PRIN = "PRIN"
    FAFA = "FAFA"


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


class InventoryItem(BaseModel):
    """One product or ingredient the business sells or uses."""

    name: str
    kind: Literal["product", "ingredient"]
    ingredients: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)
    brand: str | None = None
    supplier: str | None = None


class BusinessProfile(BaseModel):
    """The fictional demo business and its inventory."""

    business_id: str
    name: str
    inventory: list[InventoryItem]
    handled_allergens: list[str] = Field(default_factory=list)
