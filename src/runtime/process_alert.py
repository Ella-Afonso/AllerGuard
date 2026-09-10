"""Match → deterministic gate → durable audit. No notifications or watermark commits."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from src.agents.matcher import match_alert
from src.config import Settings
from src.domain.audit_identity import ASSESSMENT_POLICY_VERSION, assessment_id
from src.domain.models import (
    Alert,
    AssessmentMode,
    AuditAppendResult,
    AuditEntry,
    AuditEvent,
    BusinessProfile,
    GateDecision,
    MatchResult,
    ProcessedAlert,
)
from src.domain.tiers import TIER_RANK, deterministic_floor
from src.safety.gate import gate
from src.tools.audit import append_audit_entry, get_audit_entry

logger = logging.getLogger(__name__)
AssessmentFunction = Callable[[Alert, BusinessProfile], MatchResult]


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
) -> ProcessedAlert:
    """Return a receipt aligned with the persisted audit row, not local proposal state."""
    entry = stored.entry
    if entry.event is AuditEvent.MATCH_ERROR:
        return ProcessedAlert(match_result=None, decision=entry.decision, audit=stored)
    if fresh_result is not None and stored.created:
        if fresh_result.tier is not entry.tier:
            raise ValueError("Fresh match result tier does not match the stored audit entry.")
        return ProcessedAlert(
            match_result=fresh_result,
            decision=entry.decision,
            audit=stored,
        )
    return ProcessedAlert(
        match_result=_match_result_from_decision(alert, business, entry),
        decision=entry.decision,
        audit=stored,
    )


def process_alert(
    alert: Alert,
    business: BusinessProfile,
    *,
    timestamp: datetime,
    settings: Settings | None = None,
    assessor: AssessmentFunction | None = None,
) -> ProcessedAlert:
    """Return the stored decision; injected assessors are explicitly labelled.

    Cache only successful assessments. Errors append a separate event, so a later
    successful retry adds a decision without erasing the failure. An audit outage
    propagates: never return a successful receipt for an unrecorded decision.
    """
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must include a timezone.")
    resolved = settings or Settings.from_environment()
    mode = AssessmentMode.BEDROCK if assessor is None else AssessmentMode.INJECTED
    model_id = resolved.bedrock_model_id if assessor is None else "injected-proposal"
    identity = assessment_id(alert, business, model_id=model_id, mode=mode)
    prior = get_audit_entry(business.business_id, f"{identity}#match_decision", resolved)
    if prior is not None:
        return _processed_from_stored(
            alert,
            business,
            AuditAppendResult(entry=prior, created=False),
        )

    result: MatchResult | None = None
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
    logger.info(
        "processed alert=%s decision=%s event=%s reused=%s",
        alert.id,
        stored.entry.decision.value,
        stored.entry.event.value,
        not stored.created,
    )
    return _processed_from_stored(alert, business, stored, fresh_result=result)
