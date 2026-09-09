"""Seed the fictional AllerGuard demo café into DynamoDB."""

from __future__ import annotations

from src.config import Settings
from src.domain.models import BusinessProfile, InventoryItem
from src.tools.inventory import ensure_business_table, seed_business


def build_demo_profile() -> BusinessProfile:
    """Return the fictional café profile used by the replay demonstration."""
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


def main() -> None:
    """Create the table if needed and seed the fictional café."""
    settings = Settings.from_environment()
    profile = build_demo_profile()

    ensure_business_table(settings)
    seed_business(profile)

    print(f"Seeded business '{profile.business_id}' into '{settings.dynamodb_table_businesses}'.")


if __name__ == "__main__":
    main()
