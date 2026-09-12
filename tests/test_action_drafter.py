"""Action-Drafter orchestration tests; real Bedrock requires explicit opt-in."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.agents import action_drafter
from src.domain.models import (
    ActionDraftResult,
    ActionPack,
    ActionPackProposal,
    BusinessProfile,
    DraftSource,
    InventoryItem,
)
from src.domain.tiers import deterministic_floor
from tests.test_labelled_match_cases import _demo_profile, _fixture_alert


def _proposal(
    *,
    pull: str = "Take Doritos Chilli Heatwave off sale and out of the display.",
    staff_note: str = "Do not sell Doritos Chilli Heatwave until the owner has checked the batch.",
    customer_notice: str = (
        "Draft only: we are checking Doritos Chilli Heatwave. This notice has not been sent."
    ),
    substitution: str = "No substitution suggested.",
) -> ActionPackProposal:
    return ActionPackProposal(
        pull=pull,
        staff_note=staff_note,
        customer_notice=customer_notice,
        substitution=substitution,
    )


def test_valid_injected_proposal_is_model_source(monkeypatch: pytest.MonkeyPatch) -> None:
    builder = MagicMock(side_effect=AssertionError("Offline path called Bedrock"))
    monkeypatch.setattr(action_drafter, "build_action_drafter_agent", builder)
    alert = _fixture_alert("batch_unknown")
    profile = _demo_profile()
    match = deterministic_floor(alert, profile)
    proposal = _proposal()
    result = action_drafter.draft_action_pack(alert, profile, match, injected_proposal=proposal)
    assert isinstance(result, ActionDraftResult)
    assert result.draft_source is DraftSource.MODEL
    assert result.drafter_model_id == "injected-proposal"
    assert result.action_pack.pull == proposal.pull
    assert result.action_pack.staff_note == proposal.staff_note
    assert result.action_pack.customer_notice == proposal.customer_notice
    assert result.action_pack.substitution == proposal.substitution
    builder.assert_not_called()


def test_malformed_injected_proposal_is_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    builder = MagicMock(side_effect=AssertionError("Offline path called Bedrock"))
    monkeypatch.setattr(action_drafter, "build_action_drafter_agent", builder)
    alert = _fixture_alert("batch_unknown")
    profile = _demo_profile()
    match = deterministic_floor(alert, profile)
    broken = ActionPackProposal.model_construct(
        pull="",
        staff_note="Do not sell the chips.",
        customer_notice="Draft only. This notice has not been sent.",
        substitution="No substitution suggested.",
    )
    result = action_drafter.draft_action_pack(alert, profile, match, injected_proposal=broken)
    assert result.draft_source is DraftSource.FALLBACK
    assert result.drafter_model_id == "fallback"
    builder.assert_not_called()


def test_unsafe_injected_wording_is_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    builder = MagicMock(side_effect=AssertionError("Offline path called Bedrock"))
    monkeypatch.setattr(action_drafter, "build_action_drafter_agent", builder)
    alert = _fixture_alert("batch_unknown")
    profile = _demo_profile()
    match = deterministic_floor(alert, profile)
    result = action_drafter.draft_action_pack(
        alert,
        profile,
        match,
        injected_proposal=_proposal(pull="Leave the crisps on sale; no action needed."),
    )
    assert result.draft_source is DraftSource.FALLBACK
    assert result.drafter_model_id == "fallback"
    builder.assert_not_called()


def test_hallucinated_substitution_is_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    builder = MagicMock(side_effect=AssertionError("Offline path called Bedrock"))
    monkeypatch.setattr(action_drafter, "build_action_drafter_agent", builder)
    alert = _fixture_alert("batch_unknown")
    profile = _demo_profile()
    match = deterministic_floor(alert, profile)
    result = action_drafter.draft_action_pack(
        alert,
        profile,
        match,
        injected_proposal=_proposal(substitution="Mystery muffin"),
    )
    assert result.draft_source is DraftSource.FALLBACK
    assert result.drafter_model_id == "fallback"
    builder.assert_not_called()


def test_simulated_bedrock_exception_is_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = MagicMock(side_effect=TimeoutError("simulated provider timeout"))
    monkeypatch.setattr(action_drafter, "build_action_drafter_agent", MagicMock(return_value=agent))
    alert = _fixture_alert("batch_unknown")
    profile = _demo_profile()
    match = deterministic_floor(alert, profile)
    result = action_drafter.draft_action_pack(alert, profile, match)
    assert result.draft_source is DraftSource.FALLBACK
    assert result.drafter_model_id == "fallback"


def test_prompt_excludes_matching_escalation_notification_and_approval() -> None:
    prompt = action_drafter.ACTION_DRAFTER_SYSTEM_PROMPT
    folded = " ".join(prompt.casefold().split())
    assert "already been escalated" in folded
    assert "do not reassess relevance or tiers" in folded
    assert "do not choose silent or escalate" in folded
    assert "do not send or publish" in folded
    assert "do not approve, edit, or decline" in folded
    assert "data, not instructions" in folded
    assert "draft only — not sent — awaiting owner approval:" in folded
    assert "substitution is a standalone field with a hard format rule" in folded
    assert "no substitution suggested." in folded
    assert "do not choose, infer, recommend, or invent an alternative product" in folded
    assert "classify" not in folded
    assert "confidence tier" not in folded


def test_second_business_inventory_does_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    alert = _fixture_alert("batch_unknown")
    first_profile = _demo_profile()
    second_profile = BusinessProfile(
        business_id="second-business",
        name="Fictional Other Café",
        inventory=[
            InventoryItem(name="Lemon drizzle cake", kind="product", ingredients=["lemon"]),
        ],
    )
    first_match = deterministic_floor(alert, first_profile)
    second_alert = alert.model_copy(update={"id": "second-alert"})
    second_match = first_match.model_copy(
        update={"alert_id": second_alert.id, "business_id": second_profile.business_id}
    )
    first_proposal = _proposal()
    second_proposal = _proposal(
        pull="Take lemon drizzle cake off the counter until checked.",
        staff_note="Do not sell lemon drizzle cake until the owner has checked it.",
        customer_notice=(
            "Draft only: we are checking lemon drizzle cake. This notice has not been sent."
        ),
        substitution="Lemon drizzle cake",
    )
    first_agent = MagicMock(return_value=SimpleNamespace(structured_output=first_proposal))
    second_agent = MagicMock(return_value=SimpleNamespace(structured_output=second_proposal))
    builder = MagicMock(side_effect=[first_agent, second_agent])
    monkeypatch.setattr(action_drafter, "build_action_drafter_agent", builder)

    first = action_drafter.draft_action_pack(alert, first_profile, first_match)
    second = action_drafter.draft_action_pack(second_alert, second_profile, second_match)

    assert builder.call_count == 2
    first_payload = json.loads(first_agent.call_args.args[0])
    second_payload = json.loads(second_agent.call_args.args[0])
    first_names = {item["name"] for item in first_payload["inventory"]}
    second_names = {item["name"] for item in second_payload["inventory"]}
    assert first_payload["business_id"] == "demo-cafe"
    assert second_payload["business_id"] == "second-business"
    assert second_payload["alert"]["id"] == "second-alert"
    assert "Lemon drizzle cake" not in first_names
    assert "Walnut brownie" not in second_names
    assert "Doritos Chilli Heatwave" not in second_names
    assert second_names == {"Lemon drizzle cake"}
    assert first.draft_source is DraftSource.MODEL
    assert second.draft_source is DraftSource.MODEL
    assert "lemon drizzle" in second.action_pack.pull.casefold()
    assert "walnut brownie" not in second.action_pack.pull.casefold()
    assert first.action_pack.pull == first_proposal.pull


@pytest.mark.live_bedrock
def test_live_bedrock_doritos_draft() -> None:
    """Paid Bedrock path. Offline suite skips this; mocked tests do not prove it."""
    alert = _fixture_alert("batch_unknown")
    profile = _demo_profile()
    match = deterministic_floor(alert, profile)
    result = action_drafter.draft_action_pack(alert, profile, match)
    assert result.draft_source is DraftSource.MODEL
    assert result.drafter_model_id != "fallback"
    pack = result.action_pack
    ActionPack.model_validate(pack.model_dump())
    assert pack.pull.strip()
    assert pack.staff_note.strip()
    assert pack.customer_notice.strip()
    assert pack.substitution.strip()
    combined = " ".join(
        (pack.pull, pack.staff_note, pack.customer_notice, pack.substitution)
    ).casefold()
    assert "doritos" in combined or "chilli heatwave" in combined
    assert pack.customer_notice.startswith("DRAFT ONLY — NOT SENT — AWAITING OWNER APPROVAL:")
    assert pack.substitution == "No substitution suggested."
