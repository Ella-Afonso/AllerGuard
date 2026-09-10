"""The complete escalation policy. Pure code, with no model or I/O."""

from src.domain.models import ConfidenceTier, GateDecision, MatchResult


def gate(result: MatchResult) -> GateDecision:
    """Only an assessed NO_MATCH is silent; everything else needs review."""
    if result.tier is ConfidenceTier.NO_MATCH:
        return GateDecision.SILENT
    return GateDecision.ESCALATE
