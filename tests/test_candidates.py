"""Tests for high-recall, pure candidate generation."""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.domain.candidates import generate_candidates
from src.domain.models import Alert, AlertType, BusinessProfile, InventoryItem, MatchDimension


def _alert(
    *,
    title: str = "Test recall",
    products: list[str] | None = None,
    allergens: list[str] | None = None,
    reporting_business: str | None = None,
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
        reporting_business=reporting_business,
    )


def _profile(
    item: InventoryItem,
    *,
    handled_allergens: list[str] | None = None,
) -> BusinessProfile:
    return BusinessProfile(
        business_id="test-cafe",
        name="Test Café",
        inventory=[item],
        handled_allergens=handled_allergens or [],
    )


def test_exact_product_generates_product_brand_candidate() -> None:
    profile = _profile(InventoryItem(name="Walnut brownie", kind="product"))

    candidates = generate_candidates(_alert(products=["Walnut Brownies"]), profile)

    assert any(
        candidate.dimension is MatchDimension.PRODUCT_BRAND
        and candidate.inventory_item_name == "Walnut brownie"
        and not candidate.fuzzy
        for candidate in candidates
    )


def test_supplier_generates_ingredient_supplier_candidate() -> None:
    profile = _profile(
        InventoryItem(
            name="Chocolate brownie",
            kind="product",
            supplier="Great Foods Ltd",
        )
    )

    candidates = generate_candidates(_alert(reporting_business="Great Foods Ltd"), profile)

    assert any(
        candidate.dimension is MatchDimension.INGREDIENT_SUPPLIER
        and candidate.inventory_item_name == "Chocolate brownie"
        for candidate in candidates
    )


def test_ingredient_in_alert_text_generates_ingredient_candidate() -> None:
    profile = _profile(
        InventoryItem(
            name="Chocolate brownie",
            kind="product",
            ingredients=["walnut"],
        )
    )

    candidates = generate_candidates(
        _alert(title="Supplier recalls a product containing undeclared walnuts"),
        profile,
    )

    assert any(
        candidate.dimension is MatchDimension.INGREDIENT_SUPPLIER
        and candidate.inventory_item_name == "Chocolate brownie"
        for candidate in candidates
    )


def test_handled_allergen_generates_business_wide_allergen_candidate() -> None:
    profile = _profile(
        InventoryItem(name="Plain biscuit", kind="product"),
        handled_allergens=["sesame"],
    )

    candidates = generate_candidates(_alert(allergens=["Sesame seeds"]), profile)

    assert any(
        candidate.dimension is MatchDimension.ALLERGEN
        and candidate.inventory_item_name is None
        and candidate.alert_span == "sesame"
        for candidate in candidates
    )


def test_category_generates_category_candidate() -> None:
    profile = _profile(
        InventoryItem(
            name="Crisps",
            kind="product",
            categories=["snack foods"],
        )
    )

    candidates = generate_candidates(_alert(title="Recall affecting snack foods"), profile)

    assert any(
        candidate.dimension is MatchDimension.CATEGORY and candidate.inventory_item_name == "Crisps"
        for candidate in candidates
    )
