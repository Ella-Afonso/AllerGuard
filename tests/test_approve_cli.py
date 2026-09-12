"""Owner CLI tests run inside one Moto persistence context."""

from __future__ import annotations

import json
from datetime import timedelta

from src.config import Settings
from src.domain.models import (
    AssessmentMode,
    AuditEntry,
    AuditEvent,
    GateDecision,
)
from src.runtime.approve import main
from src.tools.audit import append_audit_entry, list_audit_entries
from src.tools.escalation_queue import get_escalation_view, queue_escalation
from tests.audit_support import NOW
from tests.test_escalation_queue import row


def _configure(monkeypatch, settings: Settings) -> None:
    monkeypatch.setenv("AWS_REGION", settings.aws_region)
    monkeypatch.setenv("ALLERGUARD_BEDROCK_MODEL_ID", settings.bedrock_model_id)
    monkeypatch.setenv("ALLERGUARD_DYNAMODB_TABLE_AUDIT", settings.dynamodb_table_audit)
    monkeypatch.setenv("ALLERGUARD_DYNAMODB_TABLE_ESCALATIONS", settings.dynamodb_table_escalations)
    monkeypatch.setenv("ALLERGUARD_NOTIFICATION_MODE", "disabled")


def _queue_with_audit(settings: Settings, number: int = 1, *, business_id: str = "demo-cafe"):
    escalation = row(number, business_id=business_id).model_copy(
        update={"queued_at": NOW + timedelta(minutes=number)}
    )
    queue_escalation(escalation, settings)
    append_audit_entry(
        AuditEntry(
            entry_id=f"{escalation.assessment_id}#escalation_queued",
            assessment_id=escalation.assessment_id,
            timestamp=escalation.queued_at,
            business_id=escalation.business_id,
            alert_id=escalation.alert_id,
            alert_modified=escalation.alert_modified,
            alert_title=escalation.alert_title,
            source_url=escalation.source_url,
            event=AuditEvent.ESCALATION_QUEUED,
            tier=escalation.tier,
            floor_tier=escalation.floor_tier,
            decision=GateDecision.ESCALATE,
            reason=escalation.reason,
            policy_version=escalation.policy_version,
            model_id="offline-test-model",
            mode=AssessmentMode.INJECTED,
            draft_source=escalation.draft_source,
        ),
        settings,
    )
    return escalation


def test_list_show_approve_and_first_choice_is_retained(
    audit_settings, monkeypatch, capsys
) -> None:
    _configure(monkeypatch, audit_settings)
    escalation = _queue_with_audit(audit_settings)
    assert main(["--business-id", "demo-cafe", "list"]) == 0
    assert escalation.escalation_id in capsys.readouterr().out
    assert main(["--business-id", "demo-cafe", "show", escalation.escalation_id]) == 0
    assert "Original draft" in capsys.readouterr().out
    assert main(["--business-id", "demo-cafe", "approve", escalation.escalation_id]) == 0
    assert main(["--business-id", "demo-cafe", "decline", escalation.escalation_id]) == 0
    output = capsys.readouterr().out
    assert "stored first choice retained" in output
    view = get_escalation_view("demo-cafe", escalation.escalation_id, audit_settings)
    assert view is not None
    assert view.effective_status.value == "approved"
    assert len(list_audit_entries("demo-cafe", audit_settings)) == 2
    assert main(["--business-id", "demo-cafe", "list"]) == 0
    assert "Pending escalations for demo-cafe: 0" in capsys.readouterr().out


def test_edit_accepts_utf8_bom_and_preserves_original(
    audit_settings, monkeypatch, tmp_path
) -> None:
    _configure(monkeypatch, audit_settings)
    escalation = _queue_with_audit(audit_settings, 2)
    path = tmp_path / "edited.json"
    path.write_text(
        json.dumps(
            {
                "pull": "DRAFT: isolate the fictional brownie.",
                "staff_note": "DRAFT: keep it away from service.",
                "customer_notice": "DRAFT ONLY — NOT SENT — AWAITING OWNER APPROVAL: wording.",
                "substitution": "No substitution suggested.",
            }
        ),
        encoding="utf-8-sig",
    )
    assert (
        main(
            [
                "--business-id",
                "demo-cafe",
                "edit",
                escalation.escalation_id,
                "--pack-file",
                str(path),
            ]
        )
        == 0
    )
    view = get_escalation_view("demo-cafe", escalation.escalation_id, audit_settings)
    assert view is not None and view.decision_record is not None
    assert view.decision_record.edited_pack is not None
    assert view.escalation.action_pack.pull != view.decision_record.edited_pack.pull


def test_missing_id_bad_file_and_cross_business_are_nonzero(
    audit_settings, monkeypatch, tmp_path
) -> None:
    _configure(monkeypatch, audit_settings)
    escalation = _queue_with_audit(audit_settings, 3, business_id="other-cafe")
    assert main(["--business-id", "demo-cafe", "show", escalation.escalation_id]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert (
        main(
            [
                "--business-id",
                "other-cafe",
                "edit",
                escalation.escalation_id,
                "--pack-file",
                str(bad),
            ]
        )
        == 2
    )
