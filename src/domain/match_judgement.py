"""Pure validation and deterministic finalisation of untrusted Matcher proposals."""

from __future__ import annotations

import re

from pydantic import ValidationError

from src.domain.models import (
    Alert,
    BusinessProfile,
    ConfidenceTier,
    MatchCandidate,
    MatchDimension,
    MatcherProposal,
    MatchResult,
)
from src.domain.normalise import normalise_text, tokenise
from src.domain.tiers import (
    TIER_RANK,
    deterministic_floor,
    has_known_batch_intersection,
    has_recorded_batch_for_items,
    is_batch_limited,
    raise_tier_never_lower,
)


class MatcherError(ValueError):
    """Assessment failed; callers must route for review, never silently skip."""


class MatcherMalformedProposalError(MatcherError):
    """The model proposal does not satisfy the response schema."""


class MatcherInvalidEvidenceError(MatcherError):
    """Evidence is missing, stale or outside this assessment."""


class MatcherUnsupportedCertaintyError(MatcherError):
    """The cited evidence does not support the proposed certainty."""


class MatcherModelError(MatcherError):
    """The model service failed or did not return structured output."""


def parse_proposal(value: object) -> MatcherProposal:
    """Validate even existing model instances, which may have been constructed unsafely."""
    raw = value.model_dump() if isinstance(value, MatcherProposal) else value
    try:
        return MatcherProposal.model_validate(raw)
    except ValidationError as error:
        raise MatcherMalformedProposalError("Matcher returned an invalid proposal.") from error


def evidence_ceiling(
    alert: Alert,
    profile: BusinessProfile,
    cited: list[MatchCandidate],
) -> ConfidenceTier:
    """Bound certainty using only cited connections, not unrelated stronger evidence.

    Fuzzy/product-token and supplier/ingredient links support LIKELY. CONFIRMED
    requires an exact recalled product with adequate batch evidence. No model
    claim can manufacture the missing identity or batch information.
    """
    ceiling = ConfidenceTier.NO_MATCH
    businesses = {
        normalise_text(name) for name in [alert.reporting_business, *alert.other_businesses] if name
    }
    for candidate in cited:
        supported = ConfidenceTier.POSSIBLE
        for item in profile.inventory:
            if item.name != candidate.inventory_item_name:
                continue
            if candidate.dimension is MatchDimension.PRODUCT_BRAND:
                supported = ConfidenceTier.LIKELY
                exact = any(
                    candidate.alert_span == product
                    and normalise_text(product) == normalise_text(item.name)
                    for product in alert.products
                )
                if exact and (
                    not is_batch_limited(alert)
                    or has_known_batch_intersection(alert, profile, [item.name])
                ):
                    supported = ConfidenceTier.CONFIRMED
            elif candidate.dimension is MatchDimension.INGREDIENT_SUPPLIER:
                supplier = bool(
                    item.supplier
                    and normalise_text(candidate.alert_span) == normalise_text(item.supplier)
                    and normalise_text(item.supplier) in businesses
                )
                ingredient = any(
                    candidate.alert_span == ingredient_name
                    and tokenise(ingredient_name)
                    and tokenise(ingredient_name) <= tokenise(product)
                    for ingredient_name in item.ingredients
                    for product in alert.products
                )
                if supplier or ingredient:
                    supported = ConfidenceTier.LIKELY
                # Exact ingredient identity PLUS the recorded supplier is stronger
                # than either signal alone. Permit a justified model upgrade here.
                supplier_known = bool(item.supplier and normalise_text(item.supplier) in businesses)
                exact_ingredient = any(
                    candidate.alert_span == ingredient_name
                    and normalise_text(ingredient_name) == normalise_text(product)
                    for ingredient_name in item.ingredients
                    for product in alert.products
                )
                if exact_ingredient and supplier_known and not is_batch_limited(alert):
                    supported = ConfidenceTier.CONFIRMED
        ceiling = raise_tier_never_lower(ceiling, supported)
    return ceiling


def owner_fallback(floor: MatchResult, alert: Alert) -> str:
    """Provide code-owned context when a model's explanation cannot be used."""
    products = ", ".join(alert.products) or alert.title
    return f"Recall: {products}. {floor.reason}"


def _batch_uncertainty_items(
    floor: MatchResult,
    alert: Alert,
    profile: BusinessProfile,
) -> list[str]:
    """Exact stocked products whose batch-limited recall lacks a matching stock batch.

    Derived from alert/profile batch evidence, not from the model's prose.
    """
    if not is_batch_limited(alert):
        return []
    return [
        item.name
        for item in profile.inventory
        if item.name in floor.matched_items
        and any(normalise_text(product) == normalise_text(item.name) for product in alert.products)
        and not has_known_batch_intersection(alert, profile, [item.name])
    ]


def batch_uncertainty_reason(
    floor: MatchResult,
    alert: Alert,
    profile: BusinessProfile,
) -> str | None:
    """Application explanation for an exact product whose stock batch is unconfirmed.

    Missing stock-batch information is described as unknown. A recorded batch
    with no established intersection is unconfirmed, never a proven mismatch:
    the recall may be date-only, or the batch's product association ambiguous.
    """
    items = _batch_uncertainty_items(floor, alert, profile)
    if not items:
        return None
    products = ", ".join(alert.products) or alert.title
    missing = [name for name in items if not has_recorded_batch_for_items(profile, [name])]
    unconfirmed = [name for name in items if has_recorded_batch_for_items(profile, [name])]
    clauses = []
    if missing:
        clauses.append(f"your recorded stock batch for {', '.join(missing)} is unknown")
    if unconfirmed:
        clauses.append(
            "the available batch and date information does not establish whether "
            f"your stock of {', '.join(unconfirmed)} falls within this recall"
        )
    detail = "; ".join(clauses)
    return (
        f"Recall: {products}. You stock {', '.join(items)}, and the recall is "
        f"batch-limited: {detail}. Check the exact batch and best-before details "
        "before selling it."
    )


# Explicit enum tokens only. Case-insensitive "likely" / "possible" are ordinary English.
_TIER_LABEL = re.compile(
    r"\b(?:NO_MATCH|POSSIBLE|LIKELY|CONFIRMED)\b",
)
_UNSAFE_WHEN_POSITIVE = (
    "unrelated",
    "no link",
    "no connection",
    "not affected",
    "safe to sell",
    "business is safe",
    "definitely matches",
    "needs no action",
    "does not affect",
    "doesn't affect",
    "no match",
    "nothing relates",
)


def _reason_conflicts(reason: str, floor: MatchResult, profile: BusinessProfile) -> bool:
    """Flag explicit labels and unsafe reassurance. Not a complete semantic validator."""
    lower = reason.casefold()
    if _TIER_LABEL.search(reason):
        return True
    if floor.tier is not ConfidenceTier.NO_MATCH and any(
        phrase in lower for phrase in _UNSAFE_WHEN_POSITIVE
    ):
        return True
    return any(
        item.name.casefold() in lower and item.name not in floor.matched_items
        for item in profile.inventory
    )


def finalise_match(
    floor: MatchResult,
    proposal: MatcherProposal,
    *,
    alert: Alert,
    profile: BusinessProfile,
) -> MatchResult:
    """Return a validated result at least as high as the trusted floor, or raise."""
    # Recompute to reject a floor/candidate set from another request or a mutated caller.
    expected = deterministic_floor(alert, profile)
    if floor != expected:
        raise MatcherInvalidEvidenceError("Floor does not belong to these alert/profile inputs.")
    validated = parse_proposal(proposal)
    by_id = {candidate.candidate_id: candidate for candidate in floor.candidates}
    if len(set(validated.evidence_refs)) != len(validated.evidence_refs):
        raise MatcherInvalidEvidenceError("Duplicate evidence references are not allowed.")
    if any(reference not in by_id for reference in validated.evidence_refs):
        raise MatcherInvalidEvidenceError("Proposal cites evidence outside this assessment.")
    cited = [by_id[reference] for reference in validated.evidence_refs]
    if validated.proposed_tier is not ConfidenceTier.NO_MATCH and not cited:
        raise MatcherInvalidEvidenceError("A positive proposal requires cited evidence.")
    ceiling = evidence_ceiling(alert, profile, cited)
    if TIER_RANK[validated.proposed_tier] > TIER_RANK[ceiling]:
        raise MatcherUnsupportedCertaintyError(
            f"Proposed {validated.proposed_tier} exceeds cited evidence ceiling {ceiling}."
        )
    tier = raise_tier_never_lower(floor.floor_tier, validated.proposed_tier)
    blocked = TIER_RANK[validated.proposed_tier] < TIER_RANK[floor.floor_tier]
    batch_reason = batch_uncertainty_reason(floor, alert, profile)
    if batch_reason is not None:
        # Exact product, batch-limited, unconfirmed stock batch: the explanation
        # is deterministic, not the model's prose.
        reason = batch_reason
    elif blocked or _reason_conflicts(validated.reason, floor, profile):
        reason = owner_fallback(floor, alert)
    else:
        reason = validated.reason
    # No model-supplied identity, inventory list or candidate text enters the result.
    result = floor.model_copy(deep=True)
    result.tier = tier
    result.reason = reason
    return result
