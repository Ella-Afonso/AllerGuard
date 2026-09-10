"""Safety-critical labelled tests for real FSA fixture matching."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain.demo_cafe import build_demo_profile
from src.domain.models import Alert, BusinessProfile, ConfidenceTier
from src.domain.tiers import TIER_RANK, deterministic_floor
from src.tools import fsa_api
from tests.labelled_match_cases import (
    IRRELEVANT_FIXTURE_NAMES,
    RELEVANT_FIXTURE_CASES,
    RelevantFixtureCase,
)

FIXTURES_DIRECTORY = Path("fixtures")


def _fixture_alert(fixture_name: str) -> Alert:
    """Parse the first alert from one captured FSA fixture."""
    payload: object = json.loads(
        (FIXTURES_DIRECTORY / f"{fixture_name}.json").read_text(encoding="utf-8")
    )
    assert isinstance(payload, dict)

    alerts = fsa_api.parse_fsa_response(payload)
    assert alerts
    return alerts[0]


def _demo_profile() -> BusinessProfile:
    """Return the single canonical fictional café used by replay matching tests."""
    return build_demo_profile()


@pytest.mark.parametrize(
    "case",
    RELEVANT_FIXTURE_CASES,
    ids=lambda case: case.fixture_name,
)
def test_relevant_real_fixture_is_never_no_match(case: RelevantFixtureCase) -> None:
    """A real relevant recall must meet its conservative minimum tier."""
    result = deterministic_floor(_fixture_alert(case.fixture_name), _demo_profile())

    assert result.tier is not ConfidenceTier.NO_MATCH
    assert TIER_RANK[result.tier] >= TIER_RANK[case.minimum_tier]
    if case.fixture_name == "match_confirmed":
        assert result.tier is ConfidenceTier.POSSIBLE


@pytest.mark.parametrize("fixture_name", IRRELEVANT_FIXTURE_NAMES)
def test_irrelevant_real_fixture_remains_no_match(fixture_name: str) -> None:
    """Unrelated recalls prove the matcher is not escalating every alert."""
    result = deterministic_floor(_fixture_alert(fixture_name), _demo_profile())

    assert result.tier is ConfidenceTier.NO_MATCH
