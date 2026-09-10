"""Demo counters and report content come from actual Moto audit records."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.demo_gate_audit import run_demo
from src.config import Settings
from src.domain.models import AuditEvent, GateDecision
from src.tools.audit import list_audit_entries
from src.tools.audit_report import summarize_audit_entries, write_audit_report
from tests.test_audit import entry


def test_full_scenario_persisted_counts(
    audit_settings: Settings,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = tmp_path / "evidence.html"
    assert run_demo(audit_settings, scenario="full", live=False, repeat=1, report=report) == 0
    rows = list_audit_entries("demo-cafe", audit_settings)
    summary = summarize_audit_entries(rows)
    assert summary.audit_events == 5
    assert summary.distinct_assessments == 5
    assert summary.silent_decision_events == 2
    assert summary.escalation_decision_events == 3
    assert summary.error_events == 0
    assert len(rows) == 5
    assert sum(row.decision is GateDecision.SILENT for row in rows) == 2
    assert sum(row.decision is GateDecision.ESCALATE for row in rows) == 3
    assert all(row.event is AuditEvent.MATCH_DECISION for row in rows)
    output = capsys.readouterr().out
    assert "stored audit events:              5" in output
    assert "requires-review decision events:    3" in output
    assert "INJECTED PROPOSALS" in output
    html = report.read_text(encoding="utf-8")
    assert html.count('<article class="event ') == 5
    assert "Distinct assessments" in html
    for row in rows:
        assert row.entry_id in html


def test_full_scenario_replay_preserves_stored_rows_without_duplicates(
    audit_settings: Settings,
    tmp_path: Path,
) -> None:
    report = tmp_path / "evidence.html"
    run_demo(audit_settings, scenario="full", live=False, repeat=1, report=report)
    first_rows = list_audit_entries("demo-cafe", audit_settings)
    first_snapshot = [row.model_dump(mode="json") for row in first_rows]
    first_entry_ids = {row.entry_id for row in first_rows}

    run_demo(audit_settings, scenario="full", live=False, repeat=1, report=report)
    second_rows = list_audit_entries("demo-cafe", audit_settings)
    second_snapshot = [row.model_dump(mode="json") for row in second_rows]
    second_entry_ids = {row.entry_id for row in second_rows}

    assert len(second_rows) == len(first_rows) == 5
    assert second_entry_ids == first_entry_ids
    assert second_snapshot == first_snapshot

    summary = summarize_audit_entries(second_rows)
    assert summary.audit_events == 5
    assert summary.distinct_assessments == 5


def test_failure_then_recovery_preserves_error_and_adds_decision(
    audit_settings: Settings,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = tmp_path / "evidence.html"
    assert run_demo(audit_settings, scenario="failure", live=False, repeat=2, report=report) == 0
    rows = list_audit_entries("demo-cafe", audit_settings)
    summary = summarize_audit_entries(rows)
    assert summary.audit_events == 2
    assert summary.distinct_assessments == 1
    assert summary.error_events == 1
    assert summary.escalation_decision_events == 1
    assert summary.silent_decision_events == 0

    error_rows = [row for row in rows if row.event is AuditEvent.MATCH_ERROR]
    decision_rows = [row for row in rows if row.event is AuditEvent.MATCH_DECISION]
    assert len(error_rows) == 1
    assert len(decision_rows) == 1
    error_row, decision_row = error_rows[0], decision_rows[0]
    assert error_row.assessment_id == decision_row.assessment_id
    assert error_row.tier is None
    assert error_row.floor_tier is None
    assert decision_row.tier is not None
    assert "historical error row remains after recovery" in capsys.readouterr().out


def test_headline_scenario_counts_from_persisted_rows(
    audit_settings: Settings,
    tmp_path: Path,
) -> None:
    report = tmp_path / "evidence.html"
    assert run_demo(audit_settings, scenario="headline", live=False, repeat=2, report=report) == 0
    summary = summarize_audit_entries(list_audit_entries("demo-cafe", audit_settings))
    assert summary.audit_events == 3
    assert summary.distinct_assessments == 3
    assert summary.silent_decision_events == 2
    assert summary.escalation_decision_events == 1
    assert summary.error_events == 0


def test_report_does_not_mutate_persisted_audit_rows(
    audit_settings: Settings,
    tmp_path: Path,
) -> None:
    report = tmp_path / "evidence.html"
    run_demo(audit_settings, scenario="headline", live=False, repeat=1, report=report)
    before = list_audit_entries("demo-cafe", audit_settings)
    before_snapshot = [row.model_dump(mode="json") for row in before]
    write_audit_report(before, tmp_path / "rewrite.html", storage_label="Offline test")
    after = list_audit_entries("demo-cafe", audit_settings)
    assert [row.model_dump(mode="json") for row in after] == before_snapshot


def test_report_escapes_untrusted_text_and_links(tmp_path: Path) -> None:
    record = entry().model_copy(
        update={
            "alert_title": '<script>alert("poison")</script>',
            "reason": '<img src=x onerror="alert(1)">',
            "source_url": "javascript:alert(1)",
        }
    )
    path = write_audit_report([record], tmp_path / "evidence.html", storage_label="Offline")
    html = path.read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "<img src=x" not in html
    assert 'href="javascript:' not in html
    assert "&lt;script&gt;" in html


def test_report_links_to_official_fsa_only(tmp_path: Path) -> None:
    record = entry().model_copy(
        update={
            "source_url": "https://alerts.food.gov.uk/news-alerts/alert/fsa-test",
        }
    )
    path = write_audit_report([record], tmp_path / "evidence.html", storage_label="Offline")
    assert f'href="{record.source_url}"' in path.read_text(encoding="utf-8")


def test_report_rejects_food_gov_substring_without_allowlisted_hostname(tmp_path: Path) -> None:
    record = entry().model_copy(
        update={
            "source_url": "https://evil.example/food.gov.uk/phish",
        }
    )
    html = write_audit_report(
        [record], tmp_path / "evidence.html", storage_label="Offline"
    ).read_text(encoding="utf-8")
    assert "href=" not in html
    assert "evil.example" in html
