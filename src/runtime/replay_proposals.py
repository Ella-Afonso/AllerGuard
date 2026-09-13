"""Injected specialist proposals for explicitly labelled replay demonstrations."""

from src.agents.matcher import match_alert
from src.domain.action_draft import finalise_action_pack
from src.domain.models import (
    ActionPack,
    ActionPackProposal,
    Alert,
    BusinessProfile,
    MatcherProposal,
    MatchResult,
)
from src.domain.tiers import deterministic_floor


def assess_replay(alert: Alert, business: BusinessProfile) -> MatchResult:
    floor = deterministic_floor(alert, business)
    return match_alert(
        alert,
        business,
        injected_proposal=MatcherProposal(
            proposed_tier=floor.tier,
            reason=floor.reason,
            evidence_refs=[candidate.candidate_id for candidate in floor.candidates],
        ),
    )


def draft_replay(alert: Alert, business: BusinessProfile, match: MatchResult) -> ActionPack:
    return finalise_action_pack(
        ActionPackProposal(
            pull=(
                f"Check potentially affected stock against {alert.title}; "
                "isolate it pending review."
            ),
            staff_note=(
                f"Do not sell potentially affected items linked to {alert.title} until checked."
            ),
            customer_notice=(
                f"DRAFT ONLY — NOT SENT — AWAITING OWNER APPROVAL: reviewing {alert.title}."
            ),
            substitution="No substitution suggested.",
        ),
        alert,
        match,
        business,
    )
