"""Tests for the DynamoDB business inventory boundary."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from moto import mock_aws

from src.config import Settings
from src.domain.models import BusinessProfile, InventoryItem
from src.tools.inventory import ensure_business_table, get_business, seed_business


@pytest.fixture
def mocked_aws() -> Iterator[None]:
    """Run the test against Moto instead of a real AWS account."""
    with mock_aws():
        yield


@pytest.fixture
def inventory_settings(
    monkeypatch: pytest.MonkeyPatch,
    mocked_aws: None,
) -> Settings:
    """Configure a deterministic mocked DynamoDB environment."""
    monkeypatch.setenv("AWS_REGION", "eu-west-2")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv(
        "ALLERGUARD_DYNAMODB_TABLE_BUSINESSES",
        "allerguard-businesses-test",
    )

    settings = Settings.from_environment()
    ensure_business_table(settings)

    return settings


def _demo_profile() -> BusinessProfile:
    """Build the same fictional profile used by the seed script."""
    return BusinessProfile(
        business_id="demo-cafe",
        name="The Walnut & Whisk Café (fictional demo)",
        handled_allergens=[
            "cereals containing gluten",
            "eggs",
            "milk",
            "mustard",
            "tree nuts",
        ],
        inventory=[
            InventoryItem(
                name="Walnut brownie",
                kind="product",
                ingredients=[
                    "walnut",
                    "wheat flour",
                    "egg",
                    "milk",
                ],
                allergens=[
                    "cereals containing gluten",
                    "eggs",
                    "milk",
                    "tree nuts",
                ],
                brand="Walnut & Whisk",
                supplier="Fictional Bakery Supplier",
            ),
            InventoryItem(
                name="Doritos Chilli Heatwave",
                kind="product",
                ingredients=[
                    "maize",
                    "seasoning",
                    "milk",
                ],
                allergens=["milk"],
                brand="PepsiCo",
                supplier=None,
            ),
        ],
    )


def test_business_round_trip_preserves_the_full_typed_profile(
    inventory_settings: Settings,
) -> None:
    """A stored profile is returned as an equal BusinessProfile."""
    profile = _demo_profile()

    seed_business(profile)
    loaded_profile = get_business(profile.business_id)

    assert loaded_profile == profile


def test_unknown_business_returns_none(
    inventory_settings: Settings,
) -> None:
    """A missing partition key is represented as None."""
    assert get_business("business-does-not-exist") is None


def test_reseeding_the_same_business_is_idempotent(
    inventory_settings: Settings,
) -> None:
    """Writing the same business twice remains safe and readable."""
    profile = _demo_profile()

    seed_business(profile)
    seed_business(profile)

    assert get_business(profile.business_id) == profile
