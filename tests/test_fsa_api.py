"""Tests for the FSA live/replay parser."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.config import Settings
from src.domain.models import AlertType
from src.tools import fsa_api

FIXTURES_DIRECTORY = Path("fixtures")

FIXTURE_NAMES = (
    "alerts_recent",
    "match_confirmed",
    "nomatch_1",
    "nomatch_2",
    "batch_unknown",
    "allergen_nonstocked",
)


def _read_fixture(name: str) -> dict[str, object]:
    """Read one captured raw FSA JSON fixture."""
    with (FIXTURES_DIRECTORY / f"{name}.json").open(encoding="utf-8") as fixture_file:
        payload: object = json.load(fixture_file)

    assert isinstance(payload, dict)
    return payload


def _raw_alert(
    *,
    notation: str = "FSA-AA-01-2026",
    alert_type: str = "AA",
    modified: str = "2026-01-02T12:00:00Z",
    status: str = "Published",
) -> dict[str, object]:
    """Return a minimal raw FSA-shaped alert for isolated parser edge tests."""
    return {
        "@id": f"https://data.food.gov.uk/food-alerts/id/{notation}",
        "notation": notation,
        "type": [
            "https://data.food.gov.uk/food-alerts/def/Alert",
            f"https://data.food.gov.uk/food-alerts/def/{alert_type}",
        ],
        "title": "Test food alert",
        "description": "A test alert used only for parser edge-case tests.",
        "created": "2026-01-02",
        "modified": modified,
        "status": {"label": status},
        "alertURL": "https://www.food.gov.uk/news-alerts/alert/test",
        "problem": [
            {
                "allergen": [
                    {"label": "Walnut"},
                    {"label": "Peanut"},
                ]
            }
        ],
        "productDetails": [
            {"productName": "First product"},
            {"productName": "Second product"},
        ],
    }


@pytest.mark.parametrize(
    ("alert_type", "expected_type"),
    [
        ("AA", AlertType.AA),
        ("PRIN", AlertType.PRIN),
        ("FAFA", AlertType.FAFA),
    ],
)
def test_parser_extracts_specific_fsa_alert_type(
    alert_type: str,
    expected_type: AlertType,
) -> None:
    alerts = fsa_api.parse_fsa_response({"items": [_raw_alert(alert_type=alert_type)]})

    assert len(alerts) == 1
    assert alerts[0].type is expected_type


def test_parser_handles_multiple_allergens_and_products() -> None:
    alerts = fsa_api.parse_fsa_response({"items": [_raw_alert()]})

    assert alerts[0].allergens == ["Walnut", "Peanut"]
    assert alerts[0].products == ["First product", "Second product"]


def test_parser_handles_missing_optional_problem_and_product_details() -> None:
    raw_alert = _raw_alert()
    raw_alert.pop("problem")
    raw_alert.pop("productDetails")

    alerts = fsa_api.parse_fsa_response({"items": [raw_alert]})

    assert alerts[0].allergens == []
    assert alerts[0].products == []


def test_parser_accepts_one_other_business_object() -> None:
    """The FSA API may return one otherBusiness object instead of a list."""
    raw_alert = _raw_alert()
    raw_alert["otherBusiness"] = {"commonName": "Waitrose & Partners"}

    alerts = fsa_api.parse_fsa_response({"items": [raw_alert]})

    assert alerts[0].other_businesses == ["Waitrose & Partners"]


def test_parser_returns_withdrawn_alert_without_discarding_it() -> None:
    alerts = fsa_api.parse_fsa_response({"items": [_raw_alert(status="Withdrawn")]})

    assert alerts[0].status == "Withdrawn"


def test_parser_returns_empty_list_for_empty_fsa_result() -> None:
    assert fsa_api.parse_fsa_response({"items": []}) == []


def test_parser_removes_only_exact_duplicate_versions() -> None:
    first = _raw_alert()
    duplicate = _raw_alert()
    updated = _raw_alert(modified="2026-01-03T12:00:00Z")

    alerts = fsa_api.parse_fsa_response({"items": [first, duplicate, updated]})

    assert len(alerts) == 2
    assert {alert.modified for alert in alerts} == {
        datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
        datetime(2026, 1, 3, 12, 0, tzinfo=UTC),
    }


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_each_captured_fixture_parses_to_at_least_one_alert(
    fixture_name: str,
) -> None:
    alerts = fsa_api.parse_fsa_response(_read_fixture(fixture_name))

    assert alerts


def test_replay_mode_reads_the_configured_fixture() -> None:
    settings = Settings(
        aws_region="eu-west-2",
        bedrock_model_id="test-model",
        fsa_mode="replay",
        fsa_fixtures_path=FIXTURES_DIRECTORY / "alerts_recent.json",
    )

    alerts = fsa_api.load_alerts(settings)

    assert alerts
    assert all(alert.id.startswith("FSA-") for alert in alerts)


def test_live_mode_uses_the_shared_parser_without_a_network_request() -> None:
    settings = Settings(
        aws_region="eu-west-2",
        bedrock_model_id="test-model",
        fsa_mode="live",
    )

    fake_payload = {"items": [_raw_alert()]}

    alerts = fsa_api.load_alerts(
        settings,
        "2026-01-01T00:00:00Z",
        live_loader=lambda _settings, _since: fake_payload,
    )

    assert len(alerts) == 1
    assert alerts[0].id == "FSA-AA-01-2026"


def test_parser_extracts_matching_evidence_from_real_fixtures() -> None:
    """Fixtures expose the business, allergen notation, and batch evidence."""
    walnut_alert = fsa_api.parse_fsa_response(_read_fixture("match_confirmed"))[0]
    doritos_alert = fsa_api.parse_fsa_response(_read_fixture("batch_unknown"))[0]

    assert walnut_alert.reporting_business == "Waitrose & Partners"
    assert {"walnut", "nuts"} <= set(walnut_alert.allergen_notations)

    assert doritos_alert.reporting_business == "PepsiCo"
    assert doritos_alert.batches[0].batch_code == "GBC 209 184C"
