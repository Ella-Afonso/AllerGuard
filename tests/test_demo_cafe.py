"""The canonical café builder must stay pure and shared."""

from __future__ import annotations

import inspect

import src.domain.demo_cafe as demo_cafe
from src.domain.demo_cafe import build_demo_profile


def test_demo_cafe_module_has_no_aws_imports() -> None:
    source = inspect.getsource(demo_cafe)
    assert "boto3" not in source
    assert "src.tools" not in source
    assert "dynamodb" not in source.casefold()


def test_canonical_profile_keeps_demo_inventory() -> None:
    profile = build_demo_profile()
    assert profile.business_id == "demo-cafe"
    assert [item.name for item in profile.inventory] == [
        "Walnut brownie",
        "Doritos Chilli Heatwave",
    ]
    assert "tree nuts" in profile.handled_allergens
    assert "mustard" in profile.handled_allergens
