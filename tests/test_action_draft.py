"""Pure ActionPack, Escalation, and draft-finalisation contracts. No I/O."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from src.domain.action_draft import (
    ActionDraftCustomerNoticeNotDraftError,
    ActionDraftInvalidSubstitutionError,
    ActionDraftUnsafeReassuranceError,
    fallback_action_pack,
    finalise_action_pack,
)
from src.domain.demo_cafe import build_demo_profile
from src.domain.models import (
    ActionPack,
    ActionPackProposal,
    Alert,
    AlertType,
    AssessmentMode,
    AuditEntry,
    AuditEvent,
    ConfidenceTier,
    DraftSource,
    Escalation,
    EscalationStatus,
    GateDecision,
    MatchDimension,
    MatchResult,
)

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
ASSESSMENT = "a" * 64
OTHER_ASSESSMENT = "b" * 64


def _alert(*, title: str = "Undeclared peanut in walnut brownies") -> Alert:
    return Alert(
        id="FSA-AA-SYNTHETIC-2026",
        id_uri="https://example.test/alerts/FSA-AA-SYNTHETIC-2026",
        type=AlertType.AA,
        title=title,
        description="Fictional recall used only in offline draft tests.",
        created=date(2026, 9, 1),
        modified=NOW,
        status="Published",
        alert_url="https://example.test/alerts/FSA-AA-SYNTHETIC-2026",
        allergens=["peanuts"],
        products=["Walnut brownie"],
    )


def _match(alert: Alert, profile_business_id: str) -> MatchResult:
    return MatchResult(
        alert_id=alert.id,
        business_id=profile_business_id,
        tier=ConfidenceTier.LIKELY,
        floor_tier=ConfidenceTier.POSSIBLE,
        reason="The recalled brownie name matches a product on the fictional menu.",
        matched_items=["Walnut brownie"],
        dimensions=[MatchDimension.PRODUCT_BRAND],
        candidates=[],
    )


def _valid_pack() -> ActionPack:
    return ActionPack(
        pull="Remove the walnut brownie from sale and the display cabinet.",
        staff_note="Do not serve the walnut brownie until the owner has checked the batch.",
        customer_notice=(
            "Draft only: we are checking walnut brownies against a recall. "
            "This notice has not been sent."
        ),
        substitution="No substitution suggested.",
    )


def _proposal(
    *,
    pull: str = "Remove the walnut brownie from sale and the display cabinet.",
    staff_note: str = "Do not serve the walnut brownie until the owner has checked the batch.",
    customer_notice: str = (
        "Draft only: we are checking walnut brownies against a recall. "
        "This notice has not been sent."
    ),
    substitution: str = "No substitution suggested.",
) -> ActionPackProposal:
    return ActionPackProposal(
        pull=pull,
        staff_note=staff_note,
        customer_notice=customer_notice,
        substitution=substitution,
    )


def _escalation(
    *,
    escalation_id: str = ASSESSMENT,
    assessment_id: str = ASSESSMENT,
    action_pack: ActionPack | None = None,
    tier: ConfidenceTier | None = ConfidenceTier.LIKELY,
    floor_tier: ConfidenceTier | None = ConfidenceTier.POSSIBLE,
    draft_source: DraftSource = DraftSource.MODEL,
) -> Escalation:
    return Escalation(
        escalation_id=escalation_id,
        business_id="demo-cafe",
        assessment_id=assessment_id,
        alert_id="FSA-AA-SYNTHETIC-2026",
        alert_modified=NOW,
        alert_title="Undeclared peanut in walnut brownies",
        source_url="https://example.test/alerts/FSA-AA-SYNTHETIC-2026",
        status=EscalationStatus.PENDING,
        tier=tier,
        floor_tier=floor_tier,
        reason="The recalled brownie name matches a product on the fictional menu.",
        action_pack=action_pack or _valid_pack(),
        draft_source=draft_source,
        policy_version="matcher-gate-v1",
        draft_policy_version="action-draft-v1",
        drafter_model_id="injected-proposal",
        queued_at=NOW,
    )


def _audit(
    *,
    event: AuditEvent,
    decision: GateDecision,
    tier: ConfidenceTier | None,
    floor_tier: ConfidenceTier | None,
    error_type: str | None = None,
    draft_source: DraftSource | None = None,
) -> AuditEntry:
    identity = ASSESSMENT
    return AuditEntry(
        entry_id=f"{identity}#{event.value}",
        assessment_id=identity,
        timestamp=NOW,
        business_id="demo-cafe",
        alert_id="FSA-AA-SYNTHETIC-2026",
        alert_modified=NOW,
        alert_title="Undeclared peanut in walnut brownies",
        source_url="https://example.test/alerts/FSA-AA-SYNTHETIC-2026",
        event=event,
        tier=tier,
        floor_tier=floor_tier,
        decision=decision,
        reason="Synthetic audit row for draft-contract tests.",
        error_type=error_type,
        policy_version="matcher-gate-v1",
        model_id="injected-proposal",
        mode=AssessmentMode.INJECTED,
        draft_source=draft_source,
    )


@pytest.mark.parametrize("field", ["pull", "staff_note", "customer_notice", "substitution"])
def test_action_pack_rejects_blank_strings(field: str) -> None:
    payload = _valid_pack().model_dump()
    payload[field] = "   "
    with pytest.raises(ValidationError):
        ActionPack.model_validate(payload)


def test_action_pack_rejects_unknown_extra_fields() -> None:
    payload = _valid_pack().model_dump()
    payload["sent"] = True
    with pytest.raises(ValidationError):
        ActionPack.model_validate(payload)


@pytest.mark.parametrize("field", ["pull", "staff_note", "customer_notice", "substitution"])
def test_action_pack_rejects_strings_longer_than_800_characters(field: str) -> None:
    payload = _valid_pack().model_dump()
    payload[field] = "x" * 801
    with pytest.raises(ValidationError):
        ActionPack.model_validate(payload)


def test_escalation_rejects_id_different_from_assessment_id() -> None:
    with pytest.raises(ValidationError, match="escalation_id must equal assessment_id"):
        _escalation(escalation_id=OTHER_ASSESSMENT, assessment_id=ASSESSMENT)


@pytest.mark.parametrize(
    "event,tier,floor_tier,decision,error_type",
    [
        (
            AuditEvent.MATCH_DECISION,
            ConfidenceTier.LIKELY,
            ConfidenceTier.POSSIBLE,
            GateDecision.ESCALATE,
            None,
        ),
        (
            AuditEvent.MATCH_ERROR,
            None,
            None,
            GateDecision.ESCALATE,
            "MatcherModelError",
        ),
    ],
)
def test_match_events_reject_non_null_draft_source(
    event: AuditEvent,
    tier: ConfidenceTier | None,
    floor_tier: ConfidenceTier | None,
    decision: GateDecision,
    error_type: str | None,
) -> None:
    with pytest.raises(ValidationError, match="must not record a draft source"):
        _audit(
            event=event,
            decision=decision,
            tier=tier,
            floor_tier=floor_tier,
            error_type=error_type,
            draft_source=DraftSource.MODEL,
        )


def test_escalation_queued_requires_draft_source() -> None:
    with pytest.raises(ValidationError, match="must record a draft source"):
        _audit(
            event=AuditEvent.ESCALATION_QUEUED,
            decision=GateDecision.ESCALATE,
            tier=ConfidenceTier.LIKELY,
            floor_tier=ConfidenceTier.POSSIBLE,
            draft_source=None,
        )


def test_escalation_queued_requires_escalate() -> None:
    with pytest.raises(ValidationError, match="must escalate"):
        _audit(
            event=AuditEvent.ESCALATION_QUEUED,
            decision=GateDecision.SILENT,
            tier=ConfidenceTier.LIKELY,
            floor_tier=ConfidenceTier.POSSIBLE,
            draft_source=DraftSource.MODEL,
        )


def test_escalation_queued_accepts_draft_source_and_escalate() -> None:
    entry = _audit(
        event=AuditEvent.ESCALATION_QUEUED,
        decision=GateDecision.ESCALATE,
        tier=ConfidenceTier.LIKELY,
        floor_tier=ConfidenceTier.POSSIBLE,
        draft_source=DraftSource.FALLBACK,
    )
    assert entry.event is AuditEvent.ESCALATION_QUEUED
    assert entry.decision is GateDecision.ESCALATE
    assert entry.draft_source is DraftSource.FALLBACK


def test_valid_grounded_proposal_is_accepted() -> None:
    alert = _alert()
    profile = build_demo_profile()
    pack = finalise_action_pack(_proposal(), alert, _match(alert, profile.business_id), profile)
    assert pack.pull == "Remove the walnut brownie from sale and the display cabinet."
    assert pack.staff_note == (
        "Do not serve the walnut brownie until the owner has checked the batch."
    )
    assert "has not been sent" in pack.customer_notice
    assert pack.substitution == "No substitution suggested."


def test_already_sent_customer_notice_is_rejected() -> None:
    alert = _alert()
    profile = build_demo_profile()
    sent_notice = (
        "We have withdrawn the walnut brownie from sale. Customers may return it for a refund."
    )
    proposal = _proposal(customer_notice=sent_notice)
    with pytest.raises(ActionDraftCustomerNoticeNotDraftError):
        finalise_action_pack(proposal, alert, _match(alert, profile.business_id), profile)


def test_customer_notice_without_draft_word_is_rejected() -> None:
    alert = _alert()
    profile = build_demo_profile()
    proposal = _proposal(customer_notice="This notice has not been sent to customers.")
    with pytest.raises(ActionDraftCustomerNoticeNotDraftError):
        finalise_action_pack(proposal, alert, _match(alert, profile.business_id), profile)


def test_customer_notice_without_unsent_marker_is_rejected() -> None:
    alert = _alert()
    profile = build_demo_profile()
    proposal = _proposal(customer_notice="Draft only: we are checking walnut brownies.")
    with pytest.raises(ActionDraftCustomerNoticeNotDraftError):
        finalise_action_pack(proposal, alert, _match(alert, profile.business_id), profile)


@pytest.mark.parametrize(
    "customer_notice",
    [
        "Draft only. This notice has not been sent.",
        "Draft only. This notice is not published.",
        "Draft only. This wording is awaiting owner approval.",
        "Draft only. This wording is pending owner approval.",
    ],
)
def test_unsent_draft_customer_notice_markers_are_accepted(customer_notice: str) -> None:
    alert = _alert()
    profile = build_demo_profile()
    pack = finalise_action_pack(
        _proposal(customer_notice=customer_notice),
        alert,
        _match(alert, profile.business_id),
        profile,
    )
    assert pack.customer_notice == customer_notice


@pytest.mark.parametrize(
    "phrase",
    [
        "no action needed",
        "you are safe",
        "no further action",
        "the business is unaffected",
    ],
)
def test_unsafe_reassurance_is_rejected(phrase: str) -> None:
    alert = _alert()
    profile = build_demo_profile()
    proposal = _proposal(pull=f"Leave stock on sale; {phrase} after this recall.")
    with pytest.raises(ActionDraftUnsafeReassuranceError):
        finalise_action_pack(proposal, alert, _match(alert, profile.business_id), profile)


def test_substitution_not_in_inventory_is_rejected() -> None:
    alert = _alert()
    profile = build_demo_profile()
    proposal = _proposal(substitution="Mystery muffin")
    with pytest.raises(ActionDraftInvalidSubstitutionError):
        finalise_action_pack(proposal, alert, _match(alert, profile.business_id), profile)


def test_genuine_inventory_substitution_is_accepted() -> None:
    alert = _alert()
    profile = build_demo_profile()
    pack = finalise_action_pack(
        _proposal(substitution="Walnut brownie"),
        alert,
        _match(alert, profile.business_id),
        profile,
    )
    assert pack.substitution == "Walnut brownie"


def test_fallback_pack_is_complete_safe_specific_and_nonblank() -> None:
    alert = _alert(title="Undeclared peanut in walnut brownies")
    profile = build_demo_profile()
    pack = fallback_action_pack(alert, _match(alert, profile.business_id), profile)
    assert pack.pull.strip()
    assert pack.staff_note.strip()
    assert pack.customer_notice.strip()
    assert pack.substitution.strip()
    assert "Undeclared peanut in walnut brownies" in pack.pull
    assert "isolate" in pack.pull.casefold() or "remove" in pack.pull.casefold()
    assert "do not sell" in pack.staff_note.casefold()
    assert "draft" in pack.customer_notice.casefold()
    assert "has not been sent" in pack.customer_notice
    assert "no substitution" in pack.substitution.casefold()
    combined = " ".join(
        (pack.pull, pack.staff_note, pack.customer_notice, pack.substitution)
    ).casefold()
    assert "no action needed" not in combined
    assert "you are safe" not in combined
    assert "unaffected" not in combined


def test_fallback_from_error_context_does_not_invent_a_match_tier() -> None:
    alert = _alert()
    profile = build_demo_profile()
    pack = fallback_action_pack(alert, None, profile)
    assert isinstance(pack, ActionPack)
    assert not hasattr(pack, "tier")
    queued = _escalation(
        action_pack=pack,
        tier=None,
        floor_tier=None,
        draft_source=DraftSource.FALLBACK,
    )
    assert queued.tier is None
    assert queued.floor_tier is None
    assert queued.draft_source is DraftSource.FALLBACK
