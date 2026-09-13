"""The complete simulated day proves replay and export counts through real runtimes."""

import json
from datetime import date
from pathlib import Path

import pytest

from scripts import demo_diary


@pytest.mark.parametrize("mode, expected", [("none", 15), ("simulated", 16)])
def test_daily_proof(
    mode: str, expected: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_PROFILE", "must-not-be-used")
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "must-not-be-used")
    monkeypatch.setenv("ALLERGUARD_SNS_TOPIC_ARN", "must-not-be-used")
    trace = tmp_path / "trace.json"
    assert (
        demo_diary.run_demo(
            date(2026, 9, 13), mode, tmp_path / "diary.html", tmp_path / "diary.csv", trace
        )
        == 0
    )
    evidence = json.loads(trace.read_text(encoding="utf-8"))
    assert evidence["offline"] and evidence["replay_unchanged"]
    assert evidence["diary_filed_events"] == 1
    assert evidence["diary_confirmation_events"] == (mode == "simulated")
    assert evidence["csv_rows"] == evidence["export_event_count"] == expected
    assert evidence["simulated_notifications"] == 3 and evidence["pending_escalations"] == 0
    assert evidence["linked_approval_alert_ids"] == [demo_diary.DORITOS_ID]


def test_failed_proof_returns_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["demo_diary", "--date", "2026-09-13"])

    def broken(*args: object) -> int:
        raise RuntimeError("Deliberately failed proof")

    monkeypatch.setattr(demo_diary, "run_demo", broken)
    assert demo_diary.main() == 1
