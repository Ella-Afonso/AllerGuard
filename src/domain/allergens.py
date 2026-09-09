"""Controlled allergen vocabulary and canonicalisation."""

from __future__ import annotations

from src.domain.models import Allergen
from src.domain.normalise import normalise_text

ALLERGEN_IDS = frozenset(Allergen)

_RAW_ALIASES = {
    "celery": Allergen.CELERY,
    "celeriac": Allergen.CELERY,
    "cereals containing gluten": Allergen.CEREALS_CONTAINING_GLUTEN,
    "gluten": Allergen.CEREALS_CONTAINING_GLUTEN,
    "wheat": Allergen.CEREALS_CONTAINING_GLUTEN,
    "barley": Allergen.CEREALS_CONTAINING_GLUTEN,
    "rye": Allergen.CEREALS_CONTAINING_GLUTEN,
    "crustaceans": Allergen.CRUSTACEANS,
    "crustacean": Allergen.CRUSTACEANS,
    "eggs": Allergen.EGGS,
    "egg": Allergen.EGGS,
    "fish": Allergen.FISH,
    "lupin": Allergen.LUPIN,
    "milk": Allergen.MILK,
    "molluscs": Allergen.MOLLUSCS,
    "mollusc": Allergen.MOLLUSCS,
    "mustard": Allergen.MUSTARD,
    "nuts": Allergen.TREE_NUTS,
    "nut": Allergen.TREE_NUTS,
    "tree nuts": Allergen.TREE_NUTS,
    "tree nut": Allergen.TREE_NUTS,
    "walnut": Allergen.TREE_NUTS,
    "hazelnut": Allergen.TREE_NUTS,
    "almond": Allergen.TREE_NUTS,
    "cashew": Allergen.TREE_NUTS,
    "peanuts": Allergen.PEANUTS,
    "peanut": Allergen.PEANUTS,
    "groundnut": Allergen.PEANUTS,
    "sesame": Allergen.SESAME,
    "sesame seeds": Allergen.SESAME,
    "soy": Allergen.SOYBEANS,
    "soya": Allergen.SOYBEANS,
    "soybeans": Allergen.SOYBEANS,
    "sulphur dioxide": Allergen.SULPHUR_DIOXIDE_SULPHITES,
    "sulphites": Allergen.SULPHUR_DIOXIDE_SULPHITES,
    "sulfites": Allergen.SULPHUR_DIOXIDE_SULPHITES,
}

ALLERGEN_ALIASES = {normalise_text(alias): allergen for alias, allergen in _RAW_ALIASES.items()}


def canonical_allergen(value: str) -> Allergen | None:
    """Return a controlled allergen ID for an FSA or inventory value."""
    return ALLERGEN_ALIASES.get(normalise_text(value))
