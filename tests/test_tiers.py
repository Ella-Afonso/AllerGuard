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
from src.domain.tiers import (
    deterministic_floor,
    has_known_batch_intersection,
    raise_tier_never_lower,
)


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


def test_category_only_floor_is_possible() -> None:
    profile = _profile([InventoryItem(name="Crisps", kind="product", categories=["snack foods"])])
    result = deterministic_floor(_alert(title="Recall affecting snack foods"), profile)
    assert result.tier is ConfidenceTier.POSSIBLE


def test_description_only_may_contain_allergen_is_possible() -> None:
    profile = _profile([], handled_allergens=["sesame"])
    alert = _alert(products=["Cookies"])
    alert.description = "These cookies may-contain sesame seeds."
    result = deterministic_floor(alert, profile)
    assert result.tier is ConfidenceTier.POSSIBLE
    assert result.candidates[0].alert_span == "sesame"


def test_may_contain_scan_does_not_match_substrings_or_other_sentences() -> None:
    profile = _profile([], handled_allergens=["milk"])
    alert = _alert()
    alert.description = "May contain milkyway. Milk is discussed in a separate sentence."
    assert deterministic_floor(alert, profile).tier is ConfidenceTier.NO_MATCH


def test_fuzzy_only_product_floor_is_likely() -> None:
    profile = _profile([InventoryItem(name="Chocolatto", kind="product")])
    result = deterministic_floor(_alert(products=["Chocolato"]), profile)
    assert result.tier is ConfidenceTier.LIKELY
    assert result.candidates[0].fuzzy


def test_may_contain_allergen_continues_on_next_line() -> None:
    profile = _profile([], handled_allergens=["milk"])
    alert = _alert(products=["Cookies"])
    alert.description = "These cookies may contain:\nmilk."
    result = deterministic_floor(alert, profile)
    assert result.tier is ConfidenceTier.POSSIBLE
    assert result.candidates[0].alert_span == "milk"


def test_batch_from_another_recalled_product_is_not_confirmed() -> None:
    profile = _profile(
        [
            InventoryItem(
                name="Oat biscuit",
                kind="product",
                batch_codes=["CHOCO-222"],
            )
        ]
    )
    alert = _alert(
        products=["Oat biscuit", "Chocolate bar"],
        batches=[
            AlertBatch(product_name="Oat biscuit", batch_code="OAT-111"),
            AlertBatch(product_name="Chocolate bar", batch_code="CHOCO-222"),
        ],
    )
    result = deterministic_floor(alert, profile)
    assert result.tier is ConfidenceTier.LIKELY


def test_recorded_unconfirmed_batch_floor_does_not_claim_missing_data() -> None:
    """The model's input must not call an existing stock batch unknown."""
    profile = _profile([InventoryItem(name="Oat biscuit", kind="product", batch_codes=["OAT-999"])])
    alert = _alert(
        products=["Oat biscuit"],
        batches=[AlertBatch(product_name="Oat biscuit", batch_code="OAT-111")],
    )

    result = deterministic_floor(alert, profile)

    assert result.tier is ConfidenceTier.LIKELY
    assert "Oat biscuit" in result.reason
    assert "does not establish whether" in result.reason
    assert "unknown" not in result.reason.casefold()
    assert "does not match" not in result.reason.casefold()


def test_batch_matching_the_stocked_product_is_confirmed() -> None:
    profile = _profile([InventoryItem(name="Oat biscuit", kind="product", batch_codes=["OAT-111"])])
    alert = _alert(
        products=["Oat biscuit", "Chocolate bar"],
        batches=[
            AlertBatch(product_name="Oat biscuit", batch_code="OAT-111"),
            AlertBatch(product_name="Chocolate bar", batch_code="CHOCO-222"),
        ],
    )
    result = deterministic_floor(alert, profile)
    assert result.tier is ConfidenceTier.CONFIRMED


def test_unlabelled_batch_match_is_ambiguous_not_confirmed() -> None:
    profile = _profile([InventoryItem(name="Oat biscuit", kind="product", batch_codes=["OAT-111"])])
    alert = _alert(
        products=["Oat biscuit", "Chocolate bar"],
        batches=[
            AlertBatch(batch_code="OAT-111"),
            AlertBatch(product_name="Chocolate bar", batch_code="CHOCO-222"),
        ],
    )
    assert not has_known_batch_intersection(alert, profile, ["Oat biscuit"])
    assert deterministic_floor(alert, profile).tier is ConfidenceTier.LIKELY
