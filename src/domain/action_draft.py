"""Pure validation and deterministic fallback for untrusted Action-Drafter output."""

from __future__ import annotations

import re

from pydantic import ValidationError

from src.domain.models import (
    ActionDraftResult,
    ActionPack,
    ActionPackProposal,
    Alert,
    BusinessProfile,
    DraftSource,
    MatchResult,
)
from src.domain.normalise import normalise_text

UNSAFE_REASSURANCE = (
    "no action needed",
    "no action is needed",
    "no action required",
    "no action is required",
    "no further action",
    "you are safe",
    "you're safe",
    "the business is safe",
    "the business is unaffected",
    "you are unaffected",
    "unaffected",
    "not affected",
    "nothing to do",
    "all clear",
    "no need to act",
)

NO_SUBSTITUTION_NORMALISED = frozenset(
    {
        "no substitution suggested",
        "no substitution is suggested",
        "no suitable substitution",
        "no substitution available",
        "no substitution is available",
        "no substitution recommended",
    }
)

_WORD_BOUNDARY_UNSAFE = tuple(
    (phrase, re.compile(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])"))
    for phrase in UNSAFE_REASSURANCE
)


class ActionDraftError(ValueError):
    """The proposed pack cannot be used; callers must fall back, never send it."""


class ActionDraftMalformedProposalError(ActionDraftError):
    """The model proposal does not satisfy the response schema."""


class ActionDraftUnsafeReassuranceError(ActionDraftError):
    """The proposal tells the owner that no review or action is needed."""


class ActionDraftInvalidSubstitutionError(ActionDraftError):
    """Substitution is neither a no-substitution sentence nor a stocked item."""


class ActionDraftCustomerNoticeNotDraftError(ActionDraftError):
    """The customer notice is written as if it were already sent or published."""


_UNSENT_NOTICE_MARKERS = (
    "not sent",
    "not published",
    "awaiting owner approval",
    "pending owner approval",
)
_DRAFT_WORD = re.compile(r"(?<![a-z0-9])draft(?![a-z0-9])")


def parse_pack_proposal(value: object) -> ActionPackProposal:
    """Validate even existing model instances, which may have been constructed unsafely."""
    raw = value.model_dump() if isinstance(value, ActionPackProposal) else value
    try:
        return ActionPackProposal.model_validate(raw)
    except ValidationError as error:
        raise ActionDraftMalformedProposalError(
            "Action-Drafter returned an invalid proposal."
        ) from error


def fallback_action_pack(
    alert: Alert,
    match_result: MatchResult | None,
    profile: BusinessProfile,
) -> ActionPack:
    """Conservative owner-facing drafts when the model pack cannot be used.

    Does not invent a match tier. Names the recall and asks for human review.
    """
    _check_identities(alert, match_result, profile)
    label = alert.title.strip() or alert.id
    pull = (
        f"Review {label} and isolate or remove any potentially affected stock "
        "from sale and display until you have checked it."
    )
    staff_note = (
        f"Do not sell potentially affected stock linked to {label} until it has "
        "been checked. Isolate it from customers and the service counter."
    )
    customer_notice = (
        f"This is a draft customer notice about {label}. It has not been sent. "
        "Do not publish or send it until the owner approves the wording."
    )
    substitution = "No substitution suggested."
    return ActionPack(
        pull=pull,
        staff_note=staff_note,
        customer_notice=customer_notice,
        substitution=substitution,
    )


def fallback_action_draft(
    alert: Alert,
    match_result: MatchResult | None,
    profile: BusinessProfile,
) -> ActionDraftResult:
    """Typed fallback provenance for callers that must record draft source."""
    return ActionDraftResult(
        action_pack=fallback_action_pack(alert, match_result, profile),
        draft_source=DraftSource.FALLBACK,
        drafter_model_id="fallback",
    )


def finalise_action_pack(
    proposal: ActionPackProposal,
    alert: Alert,
    match_result: MatchResult | None,
    profile: BusinessProfile,
) -> ActionPack:
    """Accept a validated proposal only when it is safe to put in front of the owner."""
    _check_identities(alert, match_result, profile)
    parsed = parse_pack_proposal(proposal)
    pack = ActionPack(
        pull=parsed.pull,
        staff_note=parsed.staff_note,
        customer_notice=parsed.customer_notice,
        substitution=parsed.substitution,
    )
    _reject_unsafe_reassurance(pack)
    _require_unsent_customer_notice(pack)
    _require_valid_substitution(pack.substitution, profile)
    return pack


def _check_identities(
    alert: Alert,
    match_result: MatchResult | None,
    profile: BusinessProfile,
) -> None:
    if match_result is None:
        return
    if match_result.alert_id != alert.id or match_result.business_id != profile.business_id:
        raise ActionDraftError("Action pack identities do not match this assessment.")


def _reject_unsafe_reassurance(pack: ActionPack) -> None:
    combined = normalise_text(
        " ".join((pack.pull, pack.staff_note, pack.customer_notice, pack.substitution))
    )
    for phrase, pattern in _WORD_BOUNDARY_UNSAFE:
        if pattern.search(combined):
            raise ActionDraftUnsafeReassuranceError(
                f"Action pack must not reassure the owner with {phrase!r}."
            )


def _require_unsent_customer_notice(pack: ActionPack) -> None:
    """Reject notices that read as already sent or already published."""
    notice = normalise_text(pack.customer_notice)
    comparable = notice.replace("not been sent", "not sent")
    if _DRAFT_WORD.search(comparable) and any(
        marker in comparable for marker in _UNSENT_NOTICE_MARKERS
    ):
        return
    raise ActionDraftCustomerNoticeNotDraftError(
        "Customer notice must be an unsent draft awaiting owner approval."
    )


def _require_valid_substitution(substitution: str, profile: BusinessProfile) -> None:
    normalised = normalise_text(substitution)
    if normalised in NO_SUBSTITUTION_NORMALISED:
        return
    stocked = {normalise_text(item.name) for item in profile.inventory if item.name.strip()}
    if normalised in stocked:
        return
    raise ActionDraftInvalidSubstitutionError(
        "Substitution must name a stocked item or state that none is suggested."
    )
