"""Safe local JSON input for owner-authored ActionPack edits."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from src.domain.models import ActionPack


class DecisionInputError(ValueError):
    """The operator's edit file cannot be accepted as an ActionPack."""


def load_action_pack(path: str | Path) -> ActionPack:
    """Load and revalidate one UTF-8/UTF-8-BOM JSON ActionPack without side effects."""
    candidate = Path(path)
    try:
        raw_text = candidate.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise DecisionInputError(f"Could not read pack file: {candidate.name}") from error
    try:
        value = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise DecisionInputError(f"Pack file is not valid JSON (line {error.lineno}).") from error
    if not isinstance(value, dict):
        raise DecisionInputError("Pack file must contain a JSON object.")
    try:
        return ActionPack.model_validate(value)
    except ValidationError as error:
        fields = sorted(
            {".".join(str(part) for part in failure["loc"]) for failure in error.errors()}
        )
        detail = ", ".join(fields[:6]) or "fields"
        raise DecisionInputError(f"Pack file has invalid ActionPack fields: {detail}.") from error
