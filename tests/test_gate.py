"""Exhaustive, pure gate contract: only an assessed NO_MATCH may be silent."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.domain.models import ConfidenceTier, GateDecision, MatchResult
from src.safety.gate import gate

EXPECTED = {
    ConfidenceTier.NO_MATCH: GateDecision.SILENT,
    ConfidenceTier.POSSIBLE: GateDecision.ESCALATE,
    ConfidenceTier.LIKELY: GateDecision.ESCALATE,
    ConfidenceTier.CONFIRMED: GateDecision.ESCALATE,
}


def test_every_tier_has_an_explicit_contract() -> None:
    """Adding a fifth tier forces an explicit review of its expected outcome."""
    assert set(EXPECTED) == set(ConfidenceTier)


def _synthetic_match(tier: ConfidenceTier) -> MatchResult:
    return MatchResult(
        alert_id="synthetic",
        business_id="fictional",
        tier=tier,
        floor_tier=tier,
        reason="Synthetic gate test",
        matched_items=[],
        dimensions=[],
        candidates=[],
    )


@pytest.mark.parametrize("tier,decision", EXPECTED.items())
def test_gate_mapping(tier: ConfidenceTier, decision: GateDecision) -> None:
    assert gate(_synthetic_match(tier)) is decision


def test_gate_is_deterministic() -> None:
    result = _synthetic_match(ConfidenceTier.LIKELY)
    assert gate(result) is GateDecision.ESCALATE
    assert gate(result) is gate(result)


def test_gate_does_not_mutate_match_result() -> None:
    result = _synthetic_match(ConfidenceTier.POSSIBLE)
    before = result.model_dump()
    assert gate(result) is GateDecision.ESCALATE
    assert result.model_dump() == before


def test_gate_has_no_model_or_external_calls() -> None:
    """Guard the architectural boundary, not just the happy-path mapping."""
    path = Path(__file__).resolve().parents[1] / "src/safety/gate.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Call) for node in ast.walk(tree))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all(
        isinstance(node, ast.ImportFrom) and node.module == "src.domain.models" for node in imports
    )
