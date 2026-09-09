"""Tests for pure text and allergen normalisation."""

from __future__ import annotations

from src.domain.allergens import canonical_allergen
from src.domain.models import Allergen
from src.domain.normalise import normalise_text, tokenise


def test_normalise_text_folds_case_punctuation_whitespace_and_plurals() -> None:
    assert normalise_text("  Chocolate-Brownies!!  ") == "chocolate brownie"


def test_tokenise_removes_stopwords_and_adds_cautious_synonyms() -> None:
    tokens = tokenise("Groundnuts and raisins in the product")

    assert "and" not in tokens
    assert "product" not in tokens
    assert {"groundnut", "peanut", "raisin", "dried", "vine", "fruit"} <= tokens


def test_canonical_allergen_maps_common_fsa_and_inventory_aliases() -> None:
    assert canonical_allergen("Walnuts") is Allergen.TREE_NUTS
    assert canonical_allergen("groundnut") is Allergen.PEANUTS
    assert canonical_allergen("Soya") is Allergen.SOYBEANS
    assert canonical_allergen("not an allergen") is None
