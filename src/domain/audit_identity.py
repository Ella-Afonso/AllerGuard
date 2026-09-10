"""Stable assessment identity for safe retries and inventory revisions. No I/O."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC

from src.domain.models import Alert, AssessmentMode, BusinessProfile

# Bump when matching, prompt, evidence, or gate semantics change, so old decisions
# cannot suppress a required reassessment after a policy release.
ASSESSMENT_POLICY_VERSION = "matcher-gate-v1"


def assessment_id(
    alert: Alert,
    business: BusinessProfile,
    *,
    model_id: str,
    mode: AssessmentMode,
    policy_version: str = ASSESSMENT_POLICY_VERSION,
) -> str:
    """Hash all assessment inputs; exclude execution time and model output.

    A changed alert/version, inventory, model, policy, or proposal source gets a
    new identity. Rerunning unchanged inputs reuses the first recorded decision.
    """
    if alert.modified.tzinfo is None or alert.modified.utcoffset() is None:
        raise ValueError("Alert.modified must include a timezone.")
    payload = alert.model_dump(mode="json")
    payload["modified"] = alert.modified.astimezone(UTC).isoformat()
    canonical = json.dumps(
        {
            "alert": payload,
            "business": business.model_dump(mode="json"),
            "model": model_id,
            "mode": mode.value,
            "policy": policy_version,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
