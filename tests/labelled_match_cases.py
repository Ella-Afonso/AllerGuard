"""Labels for real FSA fixtures used to protect matching safety guarantees."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.models import ConfidenceTier


@dataclass(frozen=True)
class RelevantFixtureCase:
    """A real fixture that must never be classified as no match."""

    fixture_name: str
    minimum_tier: ConfidenceTier


RELEVANT_FIXTURE_CASES = (
    RelevantFixtureCase("match_confirmed", ConfidenceTier.POSSIBLE),
    RelevantFixtureCase("batch_unknown", ConfidenceTier.LIKELY),
    RelevantFixtureCase("allergen_nonstocked", ConfidenceTier.POSSIBLE),
)

IRRELEVANT_FIXTURE_NAMES = ("nomatch_1", "nomatch_2")
