"""Match → deterministic gate → durable audit → pending queue. No notify or approval."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from src.agents.action_drafter import draft_action_pack
from src.agents.matcher import match_alert
from src.config import Settings
from src.domain.action_draft import fallback_action_draft, finalise_action_pack, parse_pack_proposal
from src.domain.audit_identity import ASSESSMENT_POLICY_VERSION, assessment_id
from src.domain.models import (
    ActionDraftResult,
    ActionPack,
    Alert,
    AssessmentMode,
    AuditAppendResult,
    AuditEntry,
    AuditEvent,
    BusinessProfile,
    DraftSource,
    Escalation,
    EscalationAppendResult,
    EscalationStatus,
    GateDecision,
    MatchResult,
    NotificationReceipt,
    ProcessedAlert,
)
from src.domain.tiers import TIER_RANK, deterministic_floor
from src.runtime import notification as notification_runtime
from src.safety.gate import gate
from src.tools.audit import AuditPersistenceError, append_audit_entry, get_audit_entry
from src.tools.escalation_queue import get_escalation, queue_escalation

logger = logging.getLogger(__name__)
AssessmentFunction = Callable[[Alert, BusinessProfile], MatchResult]
DrafterFunction = Callable[[Alert, BusinessProfile, MatchResult], ActionPack]
DRAFT_POLICY_VERSION = "action-draft-v1"


def _match_result_from_decision(
    alert: Alert,
    business: BusinessProfile,
    stored: AuditEntry,
) -> MatchResult:
    """Rebuild a successful assessment from its audit row and hashed inputs.

    Candidate evidence and dimensions are not stored verbatim; they are
    recomputed from the same alert and inventory that produced the assessment_id.
    Stored candidate IDs and matched items must agree with that recomputation.
    """
    if stored.tier is None or stored.floor_tier is None:
        raise ValueError("Cannot rebuild a match result from an error event.")
    trusted = deterministic_floor(alert, business)
    stored_candidate_ids = set(stored.candidate_ids)
    floor_candidate_ids = {candidate.candidate_id for candidate in trusted.candidates}
    if stored_candidate_ids != floor_candidate_ids:
        raise ValueError("Stored candidate evidence does not match the recomputed floor.")
    if list(stored.matched_items) != trusted.matched_items:
        raise ValueError("Stored matched items do not match the recomputed floor.")
    if TIER_RANK[stored.tier] < TIER_RANK[stored.floor_tier]:
        raise ValueError("Stored tier is below its floor.")
    return MatchResult(
        alert_id=alert.id,
        business_id=business.business_id,
        tier=stored.tier,
        floor_tier=stored.floor_tier,
        reason=stored.reason,
        matched_items=list(stored.matched_items),
        dimensions=trusted.dimensions,
        candidates=trusted.candidates,
    )


def _processed_from_stored(
    alert: Alert,
    business: BusinessProfile,
    stored: AuditAppendResult,
    *,
    fresh_result: MatchResult | None = None,
    escalation: EscalationAppendResult | None = None,
    queue_audit: AuditAppendResult | None = None,
    notification: NotificationReceipt | None = None,
) -> ProcessedAlert:
    """Return a receipt aligned with the persisted audit row, not local proposal state."""
    entry = stored.entry
    if entry.event is AuditEvent.MATCH_ERROR:
        return ProcessedAlert(
            match_result=None,
            decision=entry.decision,
            audit=stored,
            escalation=escalation,
            queue_audit=queue_audit,
            notification=notification,
        )
    if fresh_result is not None and stored.created:
        if fresh_result.tier is not entry.tier:
            raise ValueError("Fresh match result tier does not match the stored audit entry.")
        return ProcessedAlert(
            match_result=fresh_result,
            decision=entry.decision,
            audit=stored,
            escalation=escalation,
            queue_audit=queue_audit,
            notification=notification,
        )
    return ProcessedAlert(
        match_result=_match_result_from_decision(alert, business, entry),
        decision=entry.decision,
        audit=stored,
        escalation=escalation,
        queue_audit=queue_audit,
        notification=notification,
    )


def _draft_pack(
    alert: Alert,
    business: BusinessProfile,
    result: MatchResult,
    *,
    settings: Settings,
    drafter: DrafterFunction | None,
) -> ActionDraftResult:
    """Produce a typed draft; unsafe injected output becomes the deterministic fallback."""
    if drafter is None:
        return draft_action_pack(alert, business, result, settings=settings)
    try:
        raw = drafter(alert, business, result)
        proposal = parse_pack_proposal(raw.model_dump() if isinstance(raw, ActionPack) else raw)
        pack = finalise_action_pack(proposal, alert, result, business)
        return ActionDraftResult(
            action_pack=pack,
            draft_source=DraftSource.MODEL,
            drafter_model_id="injected-proposal",
        )
    except Exception as error:
        logger.warning(
            "action_drafter_failed alert=%s error_type=%s",
            alert.id,
            type(error).__name__,
        )
        return fallback_action_draft(alert, result, business)


def _evidence_for_queued_audit(
    business_id: str,
    identity: str,
    persisted: Escalation,
    settings: Settings,
) -> AuditEntry:
    """Use the match event that matches the stored queue, not the latest local outcome."""
    event = AuditEvent.MATCH_ERROR if persisted.tier is None else AuditEvent.MATCH_DECISION
    evidence = get_audit_entry(business_id, f"{identity}#{event.value}", settings)
    if evidence is None:
        raise AuditPersistenceError(
            "Queued escalation is missing the matching match-event evidence."
        )
    return evidence


def _reuse_or_append_queued_audit(
    *,
    identity: str,
    timestamp: datetime,
    settings: Settings,
    persisted: Escalation,
    alert: Alert,
) -> AuditAppendResult:
    """Reuse a stored queued event; otherwise write one from matching evidence."""
    entry_id = f"{identity}#{AuditEvent.ESCALATION_QUEUED.value}"
    existing = get_audit_entry(persisted.business_id, entry_id, settings)
    if existing is not None:
        if existing.assessment_id != persisted.assessment_id:
            raise AuditPersistenceError(
                "Queued audit assessment identity does not match the queue."
            )
        if existing.draft_source is not persisted.draft_source:
            raise AuditPersistenceError("Queued audit draft_source does not match the queue row.")
        return AuditAppendResult(entry=existing, created=False)
    evidence = _evidence_for_queued_audit(persisted.business_id, identity, persisted, settings)
    return append_audit_entry(
        AuditEntry(
            entry_id=entry_id,
            assessment_id=identity,
            timestamp=timestamp,
            business_id=persisted.business_id,
            alert_id=alert.id,
            alert_modified=alert.modified,
            alert_title=alert.title,
            source_url=alert.alert_url or alert.id_uri,
            event=AuditEvent.ESCALATION_QUEUED,
            tier=persisted.tier,
            floor_tier=persisted.floor_tier,
            decision=GateDecision.ESCALATE,
            reason=persisted.reason,
            error_type=evidence.error_type,
            policy_version=ASSESSMENT_POLICY_VERSION,
            model_id=evidence.model_id,
            mode=evidence.mode,
            candidate_ids=evidence.candidate_ids,
            matched_items=evidence.matched_items,
            draft_source=persisted.draft_source,
        ),
        settings,
    )


def _queue_escalation_path(
    alert: Alert,
    business: BusinessProfile,
    *,
    identity: str,
    timestamp: datetime,
    settings: Settings,
    match_audit: AuditAppendResult,
    result: MatchResult | None,
    drafter: DrafterFunction | None,
) -> tuple[EscalationAppendResult, AuditAppendResult]:
    """Reuse a stored queue row when present; otherwise draft or fall back, then audit."""
    existing = get_escalation(business.business_id, identity, settings)
    if existing is not None:
        queued = EscalationAppendResult(escalation=existing, created=False)
    else:
        match_entry = match_audit.entry
        if result is None or match_entry.event is AuditEvent.MATCH_ERROR:
            draft = fallback_action_draft(alert, None, business)
        else:
            draft = _draft_pack(alert, business, result, settings=settings, drafter=drafter)
        queued = queue_escalation(
            Escalation(
                escalation_id=identity,
                business_id=business.business_id,
                assessment_id=identity,
                alert_id=alert.id,
                alert_modified=alert.modified,
                alert_title=alert.title,
                source_url=alert.alert_url or alert.id_uri,
                status=EscalationStatus.PENDING,
                tier=match_entry.tier,
                floor_tier=match_entry.floor_tier,
                reason=match_entry.reason,
                action_pack=draft.action_pack,
                draft_source=draft.draft_source,
                policy_version=ASSESSMENT_POLICY_VERSION,
                draft_policy_version=DRAFT_POLICY_VERSION,
                drafter_model_id=draft.drafter_model_id,
                queued_at=timestamp,
            ),
            settings,
        )
    persisted = queued.escalation
    queue_audit = _reuse_or_append_queued_audit(
        identity=identity,
        timestamp=timestamp,
        settings=settings,
        persisted=persisted,
        alert=alert,
    )
    return queued, queue_audit


def process_alert(
    alert: Alert,
    business: BusinessProfile,
    *,
    timestamp: datetime,
    settings: Settings | None = None,
    assessor: AssessmentFunction | None = None,
    drafter: DrafterFunction | None = None,
    notifier: notification_runtime.DeliveryFunction | None = None,
) -> ProcessedAlert:
    """Return the stored decision; injected assessors are explicitly labelled.

    Cache only successful assessments. Errors append a separate event, so a later
    successful retry adds a decision without erasing the failure. An existing
    match audit skips the Matcher but still completes the pending queue and
    queued-audit row. An audit or queue outage propagates: never return a
    successful receipt for an unrecorded decision or missing escalation.
    """
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must include a timezone.")
    resolved = settings or Settings.from_environment()
    mode = AssessmentMode.BEDROCK if assessor is None else AssessmentMode.INJECTED
    model_id = resolved.bedrock_model_id if assessor is None else "injected-proposal"
    identity = assessment_id(alert, business, model_id=model_id, mode=mode)
    prior = get_audit_entry(business.business_id, f"{identity}#match_decision", resolved)
    fresh_result: MatchResult | None = None
    if prior is not None:
        stored = AuditAppendResult(entry=prior, created=False)
        result: MatchResult | None = None
        if prior.event is AuditEvent.MATCH_DECISION and prior.tier is not None:
            result = _match_result_from_decision(alert, business, prior)
    else:
        result = None
        error_type: str | None = None
        try:
            raw = (
                match_alert(alert, business, settings=resolved)
                if assessor is None
                else assessor(alert, business)
            )
            # Also catches absent/unparseable output from a future adapter, not just
            # the typed exceptions raised by today's Matcher.
            result = MatchResult.model_validate(
                raw.model_dump(mode="python") if isinstance(raw, MatchResult) else raw
            )
            if result.alert_id != alert.id or result.business_id != business.business_id:
                raise ValueError("Matcher returned identities from another assessment.")
            trusted = deterministic_floor(alert, business)
            if (
                result.floor_tier is not trusted.floor_tier
                or TIER_RANK[result.tier] < TIER_RANK[trusted.floor_tier]
                or result.candidates != trusted.candidates
                or result.matched_items != trusted.matched_items
                or result.dimensions != trusted.dimensions
                or not result.reason.strip()
            ):
                raise ValueError("Matcher result contradicts the trusted evidence floor.")
            fresh_result = result
        except Exception as error:
            # Deliberately narrow boundary around one assessment: SDK and adapter
            # errors vary. Storage failures are OUTSIDE this block and must propagate.
            error_type = type(error).__name__
            result = None
            logger.warning("match_failed alert=%s error_type=%s", alert.id, error_type)

        event = AuditEvent.MATCH_DECISION if result is not None else AuditEvent.MATCH_ERROR
        decision = gate(result) if result is not None else GateDecision.ESCALATE
        entry = AuditEntry(
            entry_id=f"{identity}#{event.value}",
            assessment_id=identity,
            timestamp=timestamp,
            business_id=business.business_id,
            alert_id=alert.id,
            alert_modified=alert.modified,
            alert_title=alert.title,
            source_url=alert.alert_url or alert.id_uri,
            event=event,
            tier=result.tier if result else None,
            floor_tier=result.floor_tier if result else None,
            decision=decision,
            reason=result.reason
            if result
            else (
                f"Assessment could not be completed for {alert.title}. "
                "Human review is required; relevance has not been ruled out."
            ),
            error_type=error_type,
            policy_version=ASSESSMENT_POLICY_VERSION,
            model_id=model_id,
            mode=mode,
            candidate_ids=tuple(candidate.candidate_id for candidate in result.candidates)
            if result
            else (),
            matched_items=tuple(result.matched_items) if result else (),
        )
        stored = append_audit_entry(entry, resolved)
        if stored.entry.event is AuditEvent.MATCH_ERROR:
            result = None
            fresh_result = None
        elif stored.created:
            result = fresh_result
        else:
            result = _match_result_from_decision(alert, business, stored.entry)
            fresh_result = None

    logger.info(
        "processed alert=%s decision=%s event=%s reused=%s",
        alert.id,
        stored.entry.decision.value,
        stored.entry.event.value,
        not stored.created,
    )
    if stored.entry.decision is GateDecision.SILENT:
        return _processed_from_stored(alert, business, stored, fresh_result=fresh_result)

    queued, queue_audit = _queue_escalation_path(
        alert,
        business,
        identity=identity,
        timestamp=timestamp,
        settings=resolved,
        match_audit=stored,
        result=result,
        drafter=drafter,
    )
    notification_receipt = notification_runtime.notify_escalation(
        queued.escalation,
        resolved,
        timestamp,
        queued_audit=queue_audit.entry,
        delivery=notifier,
    )
    return _processed_from_stored(
        alert,
        business,
        stored,
        fresh_result=fresh_result,
        escalation=queued,
        queue_audit=queue_audit,
        notification=notification_receipt,
    )
