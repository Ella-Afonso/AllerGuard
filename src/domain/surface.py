"""Strict request shapes at the browser boundary."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.models import ActionPack, OwnerDecision


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    escalation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    choice: OwnerDecision
    pack: ActionPack | None = None

    @model_validator(mode="after")
    def edit_requires_pack(self) -> Self:
        if (self.choice is OwnerDecision.EDIT) != (self.pack is not None):
            raise ValueError("An edited pack is required only for Edit.")
        return self
