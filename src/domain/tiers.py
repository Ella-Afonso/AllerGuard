"""Pure deterministic matching-floor rules."""

from __future__ import annotations

from src.domain.candidates import generate_candidates
from src.domain.models import (
    Alert,
    AlertBatch,
    BusinessProfile,
    ConfidenceTier,
    MatchCandidate,
    MatchDimension,
    MatchResult,
)
from src.domain.normalise import normalise_text, tokenise

TIER_RANK = {
    ConfidenceTier.NO_MATCH: 0,
    ConfidenceTier.POSSIBLE: 1,
    ConfidenceTier.LIKELY: 2,
    ConfidenceTier.CONFIRMED: 3,
}


def is_batch_limited(alert: Alert) -> bool:
    """Return whether the FSA alert specifies any batch-limiting information."""
    return any(
        value
        for batch in alert.batches
        for value in [
            batch.batch_code,
            batch.lot_number,
            batch.use_by_description,
            batch.best_before_description,
        ]
    )


def _exact_product_items(
    alert: Alert,
    profile: BusinessProfile,
) -> list[str]:
    return [
        item.name
        for item in profile.inventory
        if any(normalise_text(product) == normalise_text(item.name) for product in alert.products)
    ]


def _normalised_product_name(value: str) -> str:
    return normalise_text(value.removeprefix("Name:"))


def _batch_code_values(batch: AlertBatch) -> list[str]:
    return [value for value in [batch.batch_code, batch.lot_number] if value]


def _batch_matches_item(
    batch: AlertBatch,
    item_name: str,
    exact_item_names: list[str],
    alert_products: list[str],
) -> bool:
    """A batch counts only when it is associated with the matched product.

    An unlabelled batch on a multi-product alert is ambiguous, not confirming.
    """
    if not batch.product_name:
        return len(exact_item_names) == 1 and len(alert_products) == 1
    batch_product = _normalised_product_name(batch.product_name)
    return batch_product == normalise_text(item_name)


def has_known_batch_intersection(
    alert: Alert,
    profile: BusinessProfile,
    item_names: list[str],
) -> bool:
    """Return whether recorded stock batches intersect the same product's batch codes."""
    exact_items = [item for item in profile.inventory if item.name in item_names]

    return any(
        normalise_text(batch_code) in {normalise_text(code) for code in item.batch_codes}
        for batch in alert.batches
        for batch_code in _batch_code_values(batch)
        for item in exact_items
        if _batch_matches_item(batch, item.name, item_names, alert.products)
    )


def has_recorded_batch_for_items(
    profile: BusinessProfile,
    item_names: list[str],
) -> bool:
    """Return whether the inventory records any batch code for the matched items."""
    return any(item.batch_codes for item in profile.inventory if item.name in item_names)


def _strong_ingredient_or_supplier_link(
    alert: Alert,
    profile: BusinessProfile,
) -> bool:
    alert_businesses = {
        normalise_text(value)
        for value in [alert.reporting_business, *alert.other_businesses]
        if value
    }

    for item in profile.inventory:
        if item.supplier and normalise_text(item.supplier) in alert_businesses:
            return True

        for ingredient in item.ingredients:
            ingredient_tokens = tokenise(ingredient)

            if any(
                ingredient_tokens and ingredient_tokens <= tokenise(product)
                for product in alert.products
            ):
                return True

    return False


def _matched_items(candidates: list[MatchCandidate]) -> list[str]:
    return list(
        dict.fromkeys(
            candidate.inventory_item_name
            for candidate in candidates
            if candidate.inventory_item_name is not None
        )
    )


def _dimensions(candidates: list[MatchCandidate]) -> list[MatchDimension]:
    return list(dict.fromkeys(candidate.dimension for candidate in candidates))


def _result(
    *,
    alert: Alert,
    profile: BusinessProfile,
    tier: ConfidenceTier,
    reason: str,
    candidates: list[MatchCandidate],
) -> MatchResult:
    return MatchResult(
        alert_id=alert.id,
        business_id=profile.business_id,
        tier=tier,
        floor_tier=tier,
        reason=reason,
        matched_items=_matched_items(candidates),
        dimensions=_dimensions(candidates),
        candidates=candidates,
    )


def deterministic_floor(
    alert: Alert,
    profile: BusinessProfile,
    candidates: list[MatchCandidate] | None = None,
) -> MatchResult:
    """Return the conservative deterministic floor for one alert.

    A future Matcher model may raise this tier, but must never lower it.
    """
    resolved_candidates = generate_candidates(alert, profile) if candidates is None else candidates

    if not resolved_candidates:
        return _result(
            alert=alert,
            profile=profile,
            tier=ConfidenceTier.NO_MATCH,
            reason=(
                "No product, ingredient, allergen, supplier, or category link "
                "was found in the recorded inventory."
            ),
            candidates=[],
        )

    exact_items = _exact_product_items(alert, profile)

    if exact_items:
        if not is_batch_limited(alert) or has_known_batch_intersection(
            alert,
            profile,
            exact_items,
        ):
            return _result(
                alert=alert,
                profile=profile,
                tier=ConfidenceTier.CONFIRMED,
                reason=(
                    f"You stock {', '.join(exact_items)}, which exactly matches "
                    "the recalled product."
                ),
                candidates=resolved_candidates,
            )

        return _result(
            alert=alert,
            profile=profile,
            tier=ConfidenceTier.LIKELY,
            reason=(
                f"You stock {', '.join(exact_items)}, but the available batch "
                "and date information does not establish whether your stock "
                "falls within this batch-limited recall."
            ),
            candidates=resolved_candidates,
        )

    if _strong_ingredient_or_supplier_link(alert, profile):
        return _result(
            alert=alert,
            profile=profile,
            tier=ConfidenceTier.LIKELY,
            reason=(
                "The recalled product or supplier strongly overlaps with an "
                "ingredient or supplier recorded in your inventory."
            ),
            candidates=resolved_candidates,
        )

    if any(
        candidate.dimension is MatchDimension.PRODUCT_BRAND for candidate in resolved_candidates
    ):
        return _result(
            alert=alert,
            profile=profile,
            tier=ConfidenceTier.LIKELY,
            reason=(
                "The recalled product or brand closely overlaps with an item "
                "recorded in your inventory."
            ),
            candidates=resolved_candidates,
        )

    allergen_candidates = [
        candidate
        for candidate in resolved_candidates
        if candidate.dimension is MatchDimension.ALLERGEN
    ]

    if allergen_candidates:
        allergen_names = ", ".join(
            sorted({candidate.alert_span.replace("_", " ") for candidate in allergen_candidates})
        )

        return _result(
            alert=alert,
            profile=profile,
            tier=ConfidenceTier.POSSIBLE,
            reason=(
                f"The alert concerns {allergen_names}, which your business "
                "handles, but the recalled product is not recorded in inventory."
            ),
            candidates=resolved_candidates,
        )

    return _result(
        alert=alert,
        profile=profile,
        tier=ConfidenceTier.POSSIBLE,
        reason=(
            "The alert has a plausible connection to a recorded inventory "
            "category, but no exact product or ingredient match was found."
        ),
        candidates=resolved_candidates,
    )


def raise_tier_never_lower(
    floor: ConfidenceTier,
    proposed: ConfidenceTier,
) -> ConfidenceTier:
    """Return the higher tier so a future model cannot lower the safety floor."""
    if TIER_RANK[proposed] > TIER_RANK[floor]:
        return proposed

    return floor
