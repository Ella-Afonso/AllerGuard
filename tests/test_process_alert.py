"""Every assessed path is audited; storage failures never claim success."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from src.config import Settings
from src.domain.action_draft import fallback_action_pack
from src.domain.audit_identity import ASSESSMENT_POLICY_VERSION, assessment_id
from src.domain.demo_cafe import build_demo_profile
from src.domain.match_judgement import MatcherModelError
from src.domain.models import (
    ActionPack,
    Alert,
    AssessmentMode,
    AuditEntry,
    AuditEvent,
    BusinessProfile,
    ConfidenceTier,
    DraftSource,
    Escalation,
    EscalationStatus,
    GateDecision,
    InventoryItem,
    MatchResult,
    ProcessedAlert,
)
from src.domain.tiers import deterministic_floor
from src.runtime import process_alert as processing
from src.tools import audit, escalation_queue
from tests.audit_support import NOW, offline_assessor
from tests.test_labelled_match_cases import _fixture_alert

LABELLED = (
    ("batch_unknown", ConfidenceTier.LIKELY, GateDecision.ESCALATE),
    ("match_confirmed", ConfidenceTier.POSSIBLE, GateDecision.ESCALATE),
    ("allergen_nonstocked", ConfidenceTier.POSSIBLE, GateDecision.ESCALATE),
    ("nomatch_1", ConfidenceTier.NO_MATCH, GateDecision.SILENT),
    ("nomatch_2", ConfidenceTier.NO_MATCH, GateDecision.SILENT),
)


def _offline_drafter(alert: Alert, business: BusinessProfile, match: MatchResult) -> ActionPack:
    return ActionPack(
        pull=f"Remove stock linked to {alert.title} from sale and display.",
        staff_note=f"Do not sell items linked to {alert.title} until checked.",
        customer_notice=(
            f"Draft only: we are checking stock against {alert.title}. "
            "This notice has not been sent."
        ),
        substitution="No substitution suggested.",
    )


def _audit_by_event(business_id: str, settings: Settings, event: AuditEvent) -> list[AuditEntry]:
    return [row for row in audit.list_audit_entries(business_id, settings) if row.event is event]


def _assert_successful_receipt(
    result: ProcessedAlert,
    *,
    tier: ConfidenceTier,
    decision: GateDecision,
    created: bool,
) -> None:
    assert result.match_result is not None
    assert result.decision is decision
    assert result.audit.entry.tier is tier
    assert result.audit.entry.decision is decision
    assert result.match_result.tier is tier
    assert result.audit.created is created
    assert result.reused is not created


def _assert_error_receipt(result: ProcessedAlert, *, error_type: str) -> None:
    assert result.match_result is None
    assert result.decision is GateDecision.ESCALATE
    assert result.audit.entry.event is AuditEvent.MATCH_ERROR
    assert result.audit.entry.tier is None
    assert result.audit.entry.floor_tier is None
    assert result.audit.entry.error_type == error_type
    assert result.escalation is not None
    assert result.queue_audit is not None
    assert result.escalation.escalation.tier is None
    assert result.escalation.escalation.floor_tier is None
    assert result.escalation.escalation.draft_source is DraftSource.FALLBACK
    assert result.queue_audit.entry.event is AuditEvent.ESCALATION_QUEUED
    assert result.queue_audit.entry.draft_source is DraftSource.FALLBACK


@pytest.mark.parametrize("fixture,tier,decision", LABELLED)
def test_labelled_relevance_precision_and_every_case_audited(
    audit_settings: Settings, fixture: str, tier: ConfidenceTier, decision: GateDecision
) -> None:
    profile = build_demo_profile()
    alert = _fixture_alert(fixture)
    drafter = MagicMock(side_effect=_offline_drafter)
    result = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=offline_assessor,
        drafter=drafter,
    )
    _assert_successful_receipt(result, tier=tier, decision=decision, created=True)
    assert result.audit.entry.reason
    trusted = deterministic_floor(alert, profile)
    assert result.match_result.candidates == trusted.candidates
    assert result.match_result.dimensions == trusted.dimensions
    decisions = _audit_by_event(profile.business_id, audit_settings, AuditEvent.MATCH_DECISION)
    queued = _audit_by_event(profile.business_id, audit_settings, AuditEvent.ESCALATION_QUEUED)
    pending = escalation_queue.list_pending(profile.business_id, audit_settings)
    if decision is GateDecision.SILENT:
        assert result.escalation is None
        assert result.queue_audit is None
        assert queued == []
        assert pending == []
        drafter.assert_not_called()
        assert decisions == [result.audit.entry]
    else:
        assert result.escalation is not None
        assert result.queue_audit is not None
        assert result.escalation.escalation.status is EscalationStatus.PENDING
        assert result.queue_audit.entry.event is AuditEvent.ESCALATION_QUEUED
        assert result.queue_audit.entry.draft_source is not None
        assert decisions == [result.audit.entry]
        assert queued == [result.queue_audit.entry]
        assert pending == [result.escalation.escalation]
        drafter.assert_called_once()


def test_same_product_batch_confirmed_is_audited(audit_settings: Settings) -> None:
    alert = _fixture_alert("batch_unknown")
    from src.domain.models import AlertBatch

    alert = alert.model_copy(
        update={
            "batches": [
                AlertBatch(
                    product_name="Doritos Chilli Heatwave",
                    batch_code="SYNTHETIC-001",
                )
            ]
        }
    )
    profile = build_demo_profile()
    profile.inventory[1].batch_codes = ["SYNTHETIC-001"]
    result = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=offline_assessor,
        drafter=_offline_drafter,
    )
    _assert_successful_receipt(
        result,
        tier=ConfidenceTier.CONFIRMED,
        decision=GateDecision.ESCALATE,
        created=True,
    )


@pytest.mark.parametrize(
    "failure",
    [
        MatcherModelError("provider failed"),
        TimeoutError("provider timeout"),
        ValueError("invalid structured data"),
    ],
)
def test_matcher_errors_escalate_with_no_invented_tier(
    audit_settings: Settings, failure: Exception
) -> None:
    broken = MagicMock(side_effect=failure)
    result = processing.process_alert(
        _fixture_alert("batch_unknown"),
        build_demo_profile(),
        timestamp=NOW,
        settings=audit_settings,
        assessor=broken,
        drafter=MagicMock(side_effect=AssertionError("MATCH_ERROR must not call Drafter")),
    )
    _assert_error_receipt(result, error_type=type(failure).__name__)
    assert _audit_by_event("demo-cafe", audit_settings, AuditEvent.MATCH_ERROR) == [
        result.audit.entry
    ]
    assert _audit_by_event("demo-cafe", audit_settings, AuditEvent.ESCALATION_QUEUED) == [
        result.queue_audit.entry
    ]


@pytest.mark.parametrize("raw", [None, {"tier": "INVALID"}, {"tier": "NO_MATCH"}])
def test_missing_or_unparseable_output_is_an_audited_error(
    audit_settings: Settings, raw: object
) -> None:
    result = processing.process_alert(
        _fixture_alert("batch_unknown"),
        build_demo_profile(),
        timestamp=NOW,
        settings=audit_settings,
        assessor=MagicMock(return_value=raw),
        drafter=MagicMock(side_effect=AssertionError("MATCH_ERROR must not call Drafter")),
    )
    assert result.audit.entry.event is AuditEvent.MATCH_ERROR
    assert result.match_result is None
    assert result.decision is GateDecision.ESCALATE


def test_retry_reuses_record_without_calling_model_again(audit_settings: Settings) -> None:
    assessor = MagicMock(side_effect=offline_assessor)
    alert, profile = _fixture_alert("batch_unknown"), build_demo_profile()
    first = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=assessor,
        drafter=_offline_drafter,
    )
    again = processing.process_alert(
        alert,
        profile,
        timestamp=NOW + timedelta(minutes=1),
        settings=audit_settings,
        assessor=assessor,
        drafter=_offline_drafter,
    )
    assert assessor.call_count == 1
    assert again.reused is True
    assert again.audit.created is False
    assert first.audit.entry == again.audit.entry
    assert again.match_result is not None
    assert again.match_result.tier is first.audit.entry.tier
    assert again.match_result.reason == first.audit.entry.reason
    trusted = deterministic_floor(alert, profile)
    assert again.match_result.candidates == trusted.candidates
    assert again.match_result.dimensions == trusted.dimensions
    assert list(again.match_result.matched_items) == list(again.audit.entry.matched_items)


def test_incompatible_stored_evidence_raises_instead_of_fabricating_success(
    audit_settings: Settings,
) -> None:
    alert, profile = _fixture_alert("batch_unknown"), build_demo_profile()
    trusted = deterministic_floor(alert, profile)
    identity = assessment_id(
        alert,
        profile,
        model_id="injected-proposal",
        mode=AssessmentMode.INJECTED,
    )
    seeded = AuditEntry(
        entry_id=f"{identity}#match_decision",
        assessment_id=identity,
        timestamp=NOW,
        business_id=profile.business_id,
        alert_id=alert.id,
        alert_modified=alert.modified,
        alert_title=alert.title,
        source_url=alert.alert_url or alert.id_uri,
        event=AuditEvent.MATCH_DECISION,
        tier=ConfidenceTier.LIKELY,
        floor_tier=trusted.floor_tier,
        decision=GateDecision.ESCALATE,
        reason="Seeded row with incompatible candidate evidence.",
        policy_version=ASSESSMENT_POLICY_VERSION,
        model_id="injected-proposal",
        mode=AssessmentMode.INJECTED,
        candidate_ids=("incompatible-candidate-id",),
        matched_items=tuple(trusted.matched_items),
    )
    audit._table(audit_settings).put_item(Item=seeded.model_dump(mode="json"))
    assessor = MagicMock(side_effect=offline_assessor)
    with pytest.raises(ValueError, match="candidate evidence"):
        processing.process_alert(
            alert,
            profile,
            timestamp=NOW,
            settings=audit_settings,
            assessor=assessor,
        )
    assessor.assert_not_called()


def test_conditional_write_race_returns_winning_stored_decision(
    audit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    alert, profile = _fixture_alert("batch_unknown"), build_demo_profile()
    table = audit._table(audit_settings)
    winning_reason = "First persisted writer wins."
    real_append = audit.append_audit_entry
    raced = False

    def racing_append(entry: AuditEntry, settings: Settings) -> audit.AuditAppendResult:
        nonlocal raced
        if not raced and entry.event is AuditEvent.MATCH_DECISION:
            raced = True
            winner = entry.model_copy(update={"reason": winning_reason})
            table.put_item(Item=winner.model_dump(mode="json"))
        return real_append(entry, settings)

    monkeypatch.setattr(processing, "append_audit_entry", racing_append)
    losing_reason = "This local assessment must not win the receipt."
    assessor = MagicMock(
        side_effect=lambda a, b: offline_assessor(a, b).model_copy(update={"reason": losing_reason})
    )
    result = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=assessor,
        drafter=_offline_drafter,
    )
    assert assessor.call_count == 1
    assert result.audit.created is False
    assert result.reused is True
    assert result.audit.entry.reason == winning_reason
    assert result.match_result is not None
    assert result.match_result.reason == winning_reason
    assert result.decision is result.audit.entry.decision


def test_failure_then_recovery_preserves_both_events(audit_settings: Settings) -> None:
    alert, profile = _fixture_alert("batch_unknown"), build_demo_profile()
    drafter = MagicMock(side_effect=_offline_drafter)
    failed = None
    for _ in range(2):
        failed = processing.process_alert(
            alert,
            profile,
            timestamp=NOW,
            settings=audit_settings,
            assessor=MagicMock(side_effect=MatcherModelError("simulated")),
            drafter=drafter,
        )
    assert failed is not None
    recovered = processing.process_alert(
        alert,
        profile,
        timestamp=NOW + timedelta(minutes=1),
        settings=audit_settings,
        assessor=offline_assessor,
        drafter=drafter,
    )
    assert drafter.call_count == 0
    assert failed.audit.entry.event is AuditEvent.MATCH_ERROR
    assert failed.match_result is None
    assert recovered.audit.entry.event is AuditEvent.MATCH_DECISION
    assert recovered.match_result is not None
    errors = _audit_by_event("demo-cafe", audit_settings, AuditEvent.MATCH_ERROR)
    decisions = _audit_by_event("demo-cafe", audit_settings, AuditEvent.MATCH_DECISION)
    queued = _audit_by_event("demo-cafe", audit_settings, AuditEvent.ESCALATION_QUEUED)
    assert errors == [failed.audit.entry]
    assert decisions == [recovered.audit.entry]
    assert len(queued) == 1
    assert failed.queue_audit is not None
    assert recovered.queue_audit is not None
    assert recovered.queue_audit.created is False
    assert recovered.queue_audit.entry == failed.queue_audit.entry
    assert queued == [failed.queue_audit.entry]
    identity = failed.audit.entry.assessment_id
    assert recovered.audit.entry.assessment_id == identity
    assert queued[0].assessment_id == identity
    assert failed.escalation is not None
    assert recovered.escalation is not None
    assert recovered.escalation.created is False
    assert recovered.escalation.escalation == failed.escalation.escalation
    assert recovered.escalation.escalation.draft_source is DraftSource.FALLBACK
    assert recovered.escalation.escalation.tier is None
    stored = escalation_queue.get_escalation(
        profile.business_id, failed.escalation.escalation.escalation_id, audit_settings
    )
    assert stored == failed.escalation.escalation
    assert len(escalation_queue.list_pending("demo-cafe", audit_settings)) == 1


def test_alert_version_change_creates_new_assessment_identity(audit_settings: Settings) -> None:
    alert, profile = _fixture_alert("nomatch_1"), build_demo_profile()
    first = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=offline_assessor,
    )
    updated = alert.model_copy(update={"modified": alert.modified + timedelta(seconds=1)})
    second = processing.process_alert(
        updated,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=offline_assessor,
    )
    assert first.audit.entry.assessment_id != second.audit.entry.assessment_id
    assert len(audit.list_audit_entries("demo-cafe", audit_settings)) == 2


def test_inventory_change_requires_new_assessment(audit_settings: Settings) -> None:
    alert, profile = _fixture_alert("nomatch_1"), build_demo_profile()
    first = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=offline_assessor,
        drafter=_offline_drafter,
    )
    profile.inventory.append(InventoryItem(name=alert.products[0], kind="product"))
    second = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=offline_assessor,
        drafter=_offline_drafter,
    )
    assert first.decision is GateDecision.SILENT
    assert second.decision is GateDecision.ESCALATE
    assert first.audit.entry.assessment_id != second.audit.entry.assessment_id
    assert len(_audit_by_event("demo-cafe", audit_settings, AuditEvent.MATCH_DECISION)) == 2
    assert len(_audit_by_event("demo-cafe", audit_settings, AuditEvent.ESCALATION_QUEUED)) == 1


def test_updated_alert_and_mode_and_policy_have_distinct_identities() -> None:
    alert, profile = _fixture_alert("nomatch_1"), build_demo_profile()

    def identify(policy_version: str = "matcher-gate-v1") -> str:
        return assessment_id(
            alert,
            profile,
            model_id="m",
            mode=AssessmentMode.INJECTED,
            policy_version=policy_version,
        )

    baseline = identify()
    assert baseline != identify(policy_version="new-policy")
    assert baseline != assessment_id(alert, profile, model_id="m", mode=AssessmentMode.BEDROCK)
    assert baseline != assessment_id(
        alert, profile, model_id="new-model", mode=AssessmentMode.INJECTED
    )
    alert.modified += timedelta(seconds=1)
    assert baseline != identify()


def test_changing_mode_creates_new_assessment_identity(
    audit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        processing,
        "match_alert",
        MagicMock(side_effect=lambda a, b, **_: offline_assessor(a, b)),
    )
    alert, profile = _fixture_alert("nomatch_1"), build_demo_profile()
    injected = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=offline_assessor,
    )
    bedrock = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=None,
    )
    assert injected.audit.entry.mode is AssessmentMode.INJECTED
    assert bedrock.audit.entry.mode is AssessmentMode.BEDROCK
    assert injected.audit.entry.assessment_id != bedrock.audit.entry.assessment_id
    assert len(audit.list_audit_entries("demo-cafe", audit_settings)) == 2


def test_changing_model_id_creates_new_assessment_identity(
    audit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        processing,
        "match_alert",
        MagicMock(side_effect=lambda a, b, **_: offline_assessor(a, b)),
    )
    alert, profile = _fixture_alert("nomatch_1"), build_demo_profile()
    first_settings = audit_settings.model_copy(update={"bedrock_model_id": "offline-model-a"})
    second_settings = audit_settings.model_copy(update={"bedrock_model_id": "offline-model-b"})
    first = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=first_settings,
        assessor=None,
    )
    second = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=second_settings,
        assessor=None,
    )
    assert first.audit.entry.model_id == "offline-model-a"
    assert second.audit.entry.model_id == "offline-model-b"
    assert first.audit.entry.assessment_id != second.audit.entry.assessment_id
    assert len(audit.list_audit_entries("demo-cafe", audit_settings)) == 2


def test_default_path_invokes_matcher_and_marks_bedrock(
    audit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = MagicMock(side_effect=lambda a, b, **_: offline_assessor(a, b))
    monkeypatch.setattr(processing, "match_alert", model)
    result = processing.process_alert(
        _fixture_alert("batch_unknown"),
        build_demo_profile(),
        timestamp=NOW,
        settings=audit_settings,
        drafter=_offline_drafter,
    )
    assert model.call_count == 1
    assert result.audit.entry.mode is AssessmentMode.BEDROCK
    assert result.audit.entry.model_id == audit_settings.bedrock_model_id


def test_audit_write_outage_raises_instead_of_returning_success(
    audit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        processing,
        "append_audit_entry",
        MagicMock(
            side_effect=audit.AuditPersistenceError("simulated storage outage"),
        ),
    )
    with pytest.raises(audit.AuditPersistenceError) as caught:
        processing.process_alert(
            _fixture_alert("batch_unknown"),
            build_demo_profile(),
            timestamp=NOW,
            settings=audit_settings,
            assessor=offline_assessor,
            drafter=_offline_drafter,
        )
    assert caught.value.decision is GateDecision.ESCALATE
    assert audit.list_audit_entries("demo-cafe", audit_settings) == []


def test_one_matcher_failure_does_not_stop_remaining_alerts(audit_settings: Settings) -> None:
    profile = build_demo_profile()
    broken_id = _fixture_alert("batch_unknown").id

    def sometimes_broken(alert: Alert, business: BusinessProfile) -> MatchResult:
        if alert.id == broken_id:
            raise MatcherModelError("simulated provider failure")
        return offline_assessor(alert, business)

    results = [
        processing.process_alert(
            _fixture_alert(name),
            profile,
            timestamp=NOW,
            settings=audit_settings,
            assessor=sometimes_broken,
            drafter=_offline_drafter,
        )
        for name in ("batch_unknown", "nomatch_1", "nomatch_2")
    ]
    assert [result.decision for result in results] == [
        GateDecision.ESCALATE,
        GateDecision.SILENT,
        GateDecision.SILENT,
    ]
    assert len(_audit_by_event("demo-cafe", audit_settings, AuditEvent.MATCH_ERROR)) == 1
    assert len(_audit_by_event("demo-cafe", audit_settings, AuditEvent.MATCH_DECISION)) == 2
    assert len(_audit_by_event("demo-cafe", audit_settings, AuditEvent.ESCALATION_QUEUED)) == 1


def test_audit_read_outage_stops_before_model_call(
    audit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = MagicMock()
    monkeypatch.setattr(
        processing,
        "get_audit_entry",
        MagicMock(
            side_effect=audit.AuditPersistenceError("cannot read"),
        ),
    )
    with pytest.raises(audit.AuditPersistenceError):
        processing.process_alert(
            _fixture_alert("nomatch_1"),
            build_demo_profile(),
            timestamp=NOW,
            settings=audit_settings,
            assessor=model,
        )
    model.assert_not_called()


def test_result_from_another_alert_is_an_audited_error(audit_settings: Settings) -> None:
    profile = build_demo_profile()
    other_result = offline_assessor(_fixture_alert("nomatch_1"), profile)
    result = processing.process_alert(
        _fixture_alert("batch_unknown"),
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=MagicMock(return_value=other_result),
        drafter=MagicMock(side_effect=AssertionError("MATCH_ERROR must not call Drafter")),
    )
    assert result.audit.entry.event is AuditEvent.MATCH_ERROR
    assert result.match_result is None
    assert result.decision is GateDecision.ESCALATE


def test_adapter_cannot_bypass_the_matching_floor(audit_settings: Settings) -> None:
    profile, alert = build_demo_profile(), _fixture_alert("batch_unknown")
    invalid = offline_assessor(alert, profile).model_copy(update={"tier": ConfidenceTier.NO_MATCH})
    result = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=MagicMock(return_value=invalid),
        drafter=MagicMock(side_effect=AssertionError("MATCH_ERROR must not call Drafter")),
    )
    assert result.audit.entry.event is AuditEvent.MATCH_ERROR
    assert result.match_result is None
    assert result.decision is GateDecision.ESCALATE


def test_five_labelled_fixtures_three_pending_two_silent(audit_settings: Settings) -> None:
    profile = build_demo_profile()
    drafter = MagicMock(side_effect=_offline_drafter)
    results = [
        processing.process_alert(
            _fixture_alert(fixture),
            profile,
            timestamp=NOW,
            settings=audit_settings,
            assessor=offline_assessor,
            drafter=drafter,
        )
        for fixture, _tier, _decision in LABELLED
    ]
    silent = [item for item in results if item.decision is GateDecision.SILENT]
    escalated = [item for item in results if item.decision is GateDecision.ESCALATE]
    assert len(silent) == 2
    assert len(escalated) == 3
    assert all(item.escalation is None and item.queue_audit is None for item in silent)
    assert all(
        item.escalation is not None
        and item.escalation.escalation.status is EscalationStatus.PENDING
        and item.queue_audit is not None
        and item.queue_audit.entry.event is AuditEvent.ESCALATION_QUEUED
        and item.queue_audit.entry.draft_source is not None
        for item in escalated
    )
    assert drafter.call_count == 3
    pending = escalation_queue.list_pending(profile.business_id, audit_settings)
    assert len(pending) == 3
    assert all(row.status is EscalationStatus.PENDING for row in pending)
    assert escalation_queue.list_pending("absent", audit_settings) == []


def test_replay_reuses_queue_and_does_not_call_drafter_again(audit_settings: Settings) -> None:
    alert, profile = _fixture_alert("batch_unknown"), build_demo_profile()
    drafter = MagicMock(side_effect=_offline_drafter)
    first = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=offline_assessor,
        drafter=drafter,
    )
    again = processing.process_alert(
        alert,
        profile,
        timestamp=NOW + timedelta(minutes=1),
        settings=audit_settings,
        assessor=offline_assessor,
        drafter=drafter,
    )
    assert drafter.call_count == 1
    assert again.reused is True
    assert again.escalation is not None
    assert again.escalation.created is False
    assert again.queue_audit is not None
    assert again.queue_audit.created is False
    assert first.escalation.escalation == again.escalation.escalation
    assert len(_audit_by_event("demo-cafe", audit_settings, AuditEvent.MATCH_DECISION)) == 1
    assert len(_audit_by_event("demo-cafe", audit_settings, AuditEvent.ESCALATION_QUEUED)) == 1
    assert len(escalation_queue.list_pending("demo-cafe", audit_settings)) == 1


def test_unsafe_injected_drafter_stores_fallback_pack(audit_settings: Settings) -> None:
    alert, profile = _fixture_alert("batch_unknown"), build_demo_profile()
    ungrounded = ActionPack(
        pull="Remove Doritos Chilli Heatwave from sale.",
        staff_note="Do not sell until the owner has checked the batch.",
        customer_notice="Draft only. This notice has not been sent.",
        substitution="Mystery muffin",
    )
    result = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=offline_assessor,
        drafter=MagicMock(return_value=ungrounded),
    )
    assert result.decision is GateDecision.ESCALATE
    assert result.escalation is not None
    assert result.escalation.created is True
    assert result.escalation.escalation.action_pack == fallback_action_pack(
        alert, result.match_result, profile
    )
    assert result.escalation.escalation.action_pack != ungrounded
    assert result.escalation.escalation.draft_source is DraftSource.FALLBACK
    assert result.escalation.escalation.drafter_model_id == "fallback"
    assert result.queue_audit is not None
    assert result.queue_audit.entry.draft_source is DraftSource.FALLBACK
    stored = escalation_queue.get_escalation(
        profile.business_id, result.escalation.escalation.escalation_id, audit_settings
    )
    assert stored is not None
    assert stored.action_pack == result.escalation.escalation.action_pack
    assert stored.draft_source is DraftSource.FALLBACK


def test_drafter_failure_queues_fallback_and_still_escalates(audit_settings: Settings) -> None:
    alert, profile = _fixture_alert("batch_unknown"), build_demo_profile()
    result = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=offline_assessor,
        drafter=MagicMock(side_effect=RuntimeError("draft failed")),
    )
    assert result.decision is GateDecision.ESCALATE
    assert result.escalation is not None
    assert result.escalation.created is True
    assert result.escalation.escalation.draft_source is DraftSource.FALLBACK
    assert result.queue_audit is not None
    assert result.queue_audit.entry.draft_source is DraftSource.FALLBACK
    assert result.escalation.escalation.action_pack == fallback_action_pack(
        alert, result.match_result, profile
    )


def test_match_error_queues_fallback_without_calling_drafter(audit_settings: Settings) -> None:
    drafter = MagicMock(side_effect=AssertionError("MATCH_ERROR must not call Drafter"))
    result = processing.process_alert(
        _fixture_alert("batch_unknown"),
        build_demo_profile(),
        timestamp=NOW,
        settings=audit_settings,
        assessor=MagicMock(side_effect=MatcherModelError("simulated")),
        drafter=drafter,
    )
    _assert_error_receipt(result, error_type="MatcherModelError")
    drafter.assert_not_called()
    pending = escalation_queue.list_pending("demo-cafe", audit_settings)
    assert len(pending) == 1
    assert pending[0].action_pack == result.escalation.escalation.action_pack


def test_partial_retry_appends_only_missing_queued_audit(audit_settings: Settings) -> None:
    alert, profile = _fixture_alert("batch_unknown"), build_demo_profile()
    trusted = deterministic_floor(alert, profile)
    identity = assessment_id(
        alert, profile, model_id="injected-proposal", mode=AssessmentMode.INJECTED
    )
    match_row = AuditEntry(
        entry_id=f"{identity}#match_decision",
        assessment_id=identity,
        timestamp=NOW,
        business_id=profile.business_id,
        alert_id=alert.id,
        alert_modified=alert.modified,
        alert_title=alert.title,
        source_url=alert.alert_url or alert.id_uri,
        event=AuditEvent.MATCH_DECISION,
        tier=trusted.tier,
        floor_tier=trusted.floor_tier,
        decision=GateDecision.ESCALATE,
        reason=trusted.reason,
        policy_version=ASSESSMENT_POLICY_VERSION,
        model_id="injected-proposal",
        mode=AssessmentMode.INJECTED,
        candidate_ids=tuple(candidate.candidate_id for candidate in trusted.candidates),
        matched_items=tuple(trusted.matched_items),
    )
    pack = _offline_drafter(alert, profile, trusted)
    queued = Escalation(
        escalation_id=identity,
        business_id=profile.business_id,
        assessment_id=identity,
        alert_id=alert.id,
        alert_modified=alert.modified,
        alert_title=alert.title,
        source_url=alert.alert_url or alert.id_uri,
        status=EscalationStatus.PENDING,
        tier=trusted.tier,
        floor_tier=trusted.floor_tier,
        reason=trusted.reason,
        action_pack=pack,
        draft_source=DraftSource.MODEL,
        policy_version=ASSESSMENT_POLICY_VERSION,
        draft_policy_version="action-draft-v1",
        drafter_model_id="injected-proposal",
        queued_at=NOW,
    )
    audit.append_audit_entry(match_row, audit_settings)
    escalation_queue.queue_escalation(queued, audit_settings)
    assessor = MagicMock(side_effect=offline_assessor)
    drafter = MagicMock(side_effect=_offline_drafter)
    result = processing.process_alert(
        alert,
        profile,
        timestamp=NOW + timedelta(minutes=1),
        settings=audit_settings,
        assessor=assessor,
        drafter=drafter,
    )
    assessor.assert_not_called()
    drafter.assert_not_called()
    assert result.audit.created is False
    assert result.audit.entry == match_row
    assert result.escalation is not None
    assert result.escalation.created is False
    assert result.escalation.escalation == queued
    assert result.queue_audit is not None
    assert result.queue_audit.created is True
    assert result.queue_audit.entry.event is AuditEvent.ESCALATION_QUEUED
    assert result.queue_audit.entry.draft_source is DraftSource.MODEL
    assert len(_audit_by_event("demo-cafe", audit_settings, AuditEvent.MATCH_DECISION)) == 1
    assert len(_audit_by_event("demo-cafe", audit_settings, AuditEvent.ESCALATION_QUEUED)) == 1


def test_queue_race_returns_winning_stored_pack(
    audit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    alert, profile = _fixture_alert("batch_unknown"), build_demo_profile()
    winning_pack = ActionPack(
        pull="Winner pack: isolate Doritos Chilli Heatwave immediately.",
        staff_note="Winner pack: do not sell Doritos Chilli Heatwave until checked.",
        customer_notice="Draft only. Winner wording has not been sent.",
        substitution="No substitution suggested.",
    )
    losing_pack = ActionPack(
        pull="Losing pack must not be stored as the queue truth.",
        staff_note="Do not treat this losing draft as persisted.",
        customer_notice="Draft only. Losing wording has not been sent.",
        substitution="No substitution suggested.",
    )
    table = escalation_queue._table(audit_settings)
    real_queue = escalation_queue.queue_escalation
    raced = False

    def racing_queue(
        item: Escalation, settings: Settings
    ) -> escalation_queue.EscalationAppendResult:
        nonlocal raced
        if not raced:
            raced = True
            winner = item.model_copy(update={"action_pack": winning_pack})
            table.put_item(Item=winner.model_dump(mode="json"))
        return real_queue(item, settings)

    monkeypatch.setattr(processing, "queue_escalation", racing_queue)
    result = processing.process_alert(
        alert,
        profile,
        timestamp=NOW,
        settings=audit_settings,
        assessor=offline_assessor,
        drafter=MagicMock(return_value=losing_pack),
    )
    assert result.escalation is not None
    assert result.escalation.created is False
    assert result.escalation.escalation.action_pack == winning_pack
    assert result.escalation.escalation.action_pack != losing_pack
    stored = escalation_queue.get_escalation(
        profile.business_id, result.escalation.escalation.escalation_id, audit_settings
    )
    assert stored is not None
    assert stored.action_pack == winning_pack
