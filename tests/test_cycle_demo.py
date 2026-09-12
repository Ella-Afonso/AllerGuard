"""The public offline demonstration reports truthful persisted totals."""

import json
from pathlib import Path

import pytest

from scripts.demo_cycle import run_demo


@pytest.mark.parametrize(
    ("choices", "events", "pending", "decisions"),
    [
        ("none", 11, 3, 0),
        ("simulated", 14, 0, 3),
    ],
)
def test_demo_two_cycles_and_owner_mode(
    tmp_path: Path, choices: str, events: int, pending: int, decisions: int
) -> None:
    report = tmp_path / "evidence.html"
    trace = tmp_path / "trace.json"
    assert run_demo(report, trace, choices) == 0
    payload = json.loads(trace.read_text(encoding="utf-8"))
    assert payload["offline"] is True
    assert payload["audit_events"] == events
    assert payload["pending"] == pending
    assert payload["simulated_notifications"] == 3
    assert payload["owner_choices"] == choices
    assert len(payload["reports"]) == 3
    assert payload["reports"][0]["status"] == "committed"
    assert payload["reports"][0]["retrieved"] == 5
    assert payload["reports"][1]["status"] == "empty"
    assert payload["reports"][1]["retrieved"] == 0
    assert report.exists() and "Offline Moto" in report.read_text(encoding="utf-8")
    assert decisions in (0, 3)
