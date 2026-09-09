"""Tests for deterministic recall-matching floors."""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.domain.models import (
    Alert,
    AlertBatch,
    AlertType,
    BusinessProfile,
    ConfidenceTier,
    InventoryItem,
)
from src.domain.tiers import deterministic_floor, raise_tier_never_lower


def _alert(
    *,
    title: str = "Test recall",
    products: list[str] | None = None,
    allergens: list[str] | None = None,
    batches: list[AlertBatch] | None = None,
) -> Alert:
    return Alert(
        id="FSA-AA-TEST-2026",
        id_uri="https://example.test/alerts/FSA-AA-TEST-2026",
        type=AlertType.AA,
        title=title,
        description=None,
        created=date(2026, 1, 1),
        modified=datetime(2026, 1, 1, tzinfo=UTC),
        status="Published",
        alert_url=None,
        allergens=allergens or [],
        products=products or [],
        batches=batches or [],
    )


def _profile(
    inventory: list[InventoryItem],
    *,
    handled_allergens: list[str] | None = None,
) -> BusinessProfile:
    return BusinessProfile(
        business_id="test-cafe",
        name="Test Café",
        inventory=inventory,
        handled_allergens=handled_allergens or [],
    )


def test_exact_product_without_batch_limit_is_confirmed() -> None:
    profile = _profile([InventoryItem(name="Walnut brownie", kind="product")])

    result = deterministic_floor(_alert(products=["Walnut Brownies"]), profile)

    assert result.tier is ConfidenceTier.CONFIRMED
    assert result.matched_items == ["Walnut brownie"]


def test_exact_product_with_unknown_batch_is_likely() -> None:
    profile = _profile([InventoryItem(name="Doritos Chilli Heatwave", kind="product")])
    alert = _alert(
        products=["Doritos Chilli Heatwave"],
        batches=[AlertBatch(batch_code="GBC 209 184C")],
    )

    result = deterministic_floor(alert, profile)

    assert result.tier is ConfidenceTier.LIKELY


def test_exact_product_with_matching_known_batch_is_confirmed() -> None:
    profile = _profile(
        [
            InventoryItem(
                name="Doritos Chilli Heatwave",
                kind="product",
                batch_codes=["GBC 209 184C"],
            )
        ]
    )
    alert = _alert(
        products=["Doritos Chilli Heatwave"],
        batches=[AlertBatch(batch_code="GBC 209 184C")],
    )

    result = deterministic_floor(alert, profile)

    assert result.tier is ConfidenceTier.CONFIRMED


def test_ingredient_only_product_match_is_likely() -> None:
    profile = _profile(
        [
            InventoryItem(
                name="Chocolate brownie",
                kind="product",
                ingredients=["walnut"],
            )
        ]
    )

    result = deterministic_floor(_alert(products=["Raw walnut halves"]), profile)

    assert result.tier is ConfidenceTier.LIKELY


def test_handled_allergen_without_stocked_product_is_possible() -> None:
    profile = _profile(
        [InventoryItem(name="Plain biscuit", kind="product")],
        handled_allergens=["sesame"],
    )

    result = deterministic_floor(_alert(allergens=["Sesame seeds"]), profile)

    assert result.tier is ConfidenceTier.POSSIBLE


def test_unrelated_alert_is_no_match() -> None:
    profile = _profile([InventoryItem(name="Walnut brownie", kind="product")])

    result = deterministic_floor(_alert(products=["Pitted black olives"]), profile)

    assert result.tier is ConfidenceTier.NO_MATCH


def test_future_model_cannot_lower_the_deterministic_floor() -> None:
    assert (
        raise_tier_never_lower(ConfidenceTier.LIKELY, ConfidenceTier.NO_MATCH)
        is ConfidenceTier.LIKELY
    )
    assert (
        raise_tier_never_lower(ConfidenceTier.POSSIBLE, ConfidenceTier.CONFIRMED)
        is ConfidenceTier.CONFIRMED
    )
