"""Canonical fictional café used by replay tests and the Matcher demo.

Pure data only: importing this module must not contact AWS.
"""

from __future__ import annotations

from src.domain.models import BusinessProfile, InventoryItem


def build_demo_profile() -> BusinessProfile:
    """Return the fictional Walnut & Whisk Café inventory for replay matching."""
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
