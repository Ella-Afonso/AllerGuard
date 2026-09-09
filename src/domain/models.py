"""Typed domain models shared across AllerGuard."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel


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
