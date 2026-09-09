"""Pure high-recall candidate generation for AllerGuard."""

from __future__ import annotations

from difflib import SequenceMatcher

from src.domain.allergens import canonical_allergen
from src.domain.models import (
    Alert,
    BusinessProfile,
    MatchCandidate,
    MatchDimension,
)
from src.domain.normalise import normalise_text, tokenise

FUZZY_THRESHOLD = 0.84


def alert_allergen_ids(alert: Alert) -> frozenset[str]:
    """Return controlled allergen IDs from FSA labels and notations."""
    values = [*alert.allergens, *alert.allergen_notations]

    return frozenset(
        allergen.value for value in values if (allergen := canonical_allergen(value)) is not None
    )


def profile_allergen_ids(profile: BusinessProfile) -> frozenset[str]:
    """Return controlled allergen IDs handled by the business."""
    values = list(profile.handled_allergens)

    for item in profile.inventory:
        values.extend(item.allergens)

    return frozenset(
        allergen.value for value in values if (allergen := canonical_allergen(value)) is not None
    )


def _token_overlap(left: str, right: str) -> frozenset[str]:
    return tokenise(left) & tokenise(right)


def _fuzzy_match(left: str, right: str) -> bool:
    normalised_left = normalise_text(left)
    normalised_right = normalise_text(right)

    if not normalised_left or not normalised_right:
        return False

    return (
        SequenceMatcher(
            None,
            normalised_left,
            normalised_right,
        ).ratio()
        >= FUZZY_THRESHOLD
    )


def _append_candidate(
    candidates: list[MatchCandidate],
    *,
    dimension: MatchDimension,
    inventory_item_name: str | None,
    alert_span: str,
    fuzzy: bool,
    evidence: str,
) -> None:
    """Append one candidate unless the same evidence is already present."""
    candidate = MatchCandidate(
        dimension=dimension,
        inventory_item_name=inventory_item_name,
        alert_span=alert_span,
        fuzzy=fuzzy,
        evidence=evidence,
    )

    if candidate not in candidates:
        candidates.append(candidate)


def generate_candidates(
    alert: Alert,
    profile: BusinessProfile,
) -> list[MatchCandidate]:
    """Find every plausible alert-to-inventory connection.

    Candidate generation intentionally over-produces. A questionable candidate can
    be handled cautiously later; a missed connection could become a false negative.
    """
    candidates: list[MatchCandidate] = []

    alert_products = alert.products
    alert_businesses = [
        business for business in [alert.reporting_business, *alert.other_businesses] if business
    ]
    alert_ingredient_text = " ".join(
        part for part in [alert.title, alert.description or "", *alert.products] if part
    )
    alert_category_tokens = tokenise(
        " ".join(part for part in [alert.title, alert.description or "", *alert.products] if part)
    )

    for item in profile.inventory:
        for product in alert_products:
            if normalise_text(product) == normalise_text(item.name):
                _append_candidate(
                    candidates,
                    dimension=MatchDimension.PRODUCT_BRAND,
                    inventory_item_name=item.name,
                    alert_span=product,
                    fuzzy=False,
                    evidence="Exact recalled product name matches the inventory item.",
                )
            elif _token_overlap(product, item.name):
                _append_candidate(
                    candidates,
                    dimension=MatchDimension.PRODUCT_BRAND,
                    inventory_item_name=item.name,
                    alert_span=product,
                    fuzzy=False,
                    evidence="Recalled product and inventory item share meaningful tokens.",
                )
            elif _fuzzy_match(product, item.name):
                _append_candidate(
                    candidates,
                    dimension=MatchDimension.PRODUCT_BRAND,
                    inventory_item_name=item.name,
                    alert_span=product,
                    fuzzy=True,
                    evidence="Recalled product and inventory item are a close fuzzy match.",
                )

        if item.brand:
            for business in alert_businesses:
                if normalise_text(business) == normalise_text(item.brand):
                    _append_candidate(
                        candidates,
                        dimension=MatchDimension.PRODUCT_BRAND,
                        inventory_item_name=item.name,
                        alert_span=business,
                        fuzzy=False,
                        evidence="Reporting business exactly matches the inventory brand.",
                    )
                elif _fuzzy_match(business, item.brand):
                    _append_candidate(
                        candidates,
                        dimension=MatchDimension.PRODUCT_BRAND,
                        inventory_item_name=item.name,
                        alert_span=business,
                        fuzzy=True,
                        evidence="Reporting business and inventory brand are a close fuzzy match.",
                    )

        for ingredient in item.ingredients:
            if _token_overlap(alert_ingredient_text, ingredient):
                _append_candidate(
                    candidates,
                    dimension=MatchDimension.INGREDIENT_SUPPLIER,
                    inventory_item_name=item.name,
                    alert_span=ingredient,
                    fuzzy=False,
                    evidence="An inventory ingredient appears in the recalled alert text.",
                )

        if item.supplier:
            for business in alert_businesses:
                if normalise_text(business) == normalise_text(item.supplier):
                    _append_candidate(
                        candidates,
                        dimension=MatchDimension.INGREDIENT_SUPPLIER,
                        inventory_item_name=item.name,
                        alert_span=business,
                        fuzzy=False,
                        evidence="Reporting business exactly matches the recorded supplier.",
                    )
                elif _fuzzy_match(business, item.supplier):
                    _append_candidate(
                        candidates,
                        dimension=MatchDimension.INGREDIENT_SUPPLIER,
                        inventory_item_name=item.name,
                        alert_span=business,
                        fuzzy=True,
                        evidence=(
                            "Reporting business and recorded supplier are a close fuzzy match."
                        ),
                    )

        for category in item.categories:
            category_tokens = tokenise(category)

            if category_tokens and category_tokens <= alert_category_tokens:
                _append_candidate(
                    candidates,
                    dimension=MatchDimension.CATEGORY,
                    inventory_item_name=item.name,
                    alert_span=category,
                    fuzzy=False,
                    evidence="The alert text contains a recorded inventory category.",
                )

    alert_ids = alert_allergen_ids(alert)
    matching_ids = alert_ids & profile_allergen_ids(profile)

    for allergen_id in sorted(matching_ids):
        matching_items: list[str | None] = [
            item.name
            for item in profile.inventory
            if allergen_id
            in {
                allergen.value
                for value in item.allergens
                if (allergen := canonical_allergen(value)) is not None
            }
        ]

        if not matching_items:
            matching_items = [None]

        for item_name in matching_items:
            _append_candidate(
                candidates,
                dimension=MatchDimension.ALLERGEN,
                inventory_item_name=item_name,
                alert_span=allergen_id,
                fuzzy=False,
                evidence="The alert allergen is handled by the business.",
            )

    return candidates
