"""Trusted local owner commands for viewing and recording escalation choices."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Sequence

from src.config import Settings
from src.domain.models import ActionPack, AuditEvent, OwnerDecision
from src.tools import audit
from src.tools.decision_input import DecisionInputError, load_action_pack
from src.tools.escalation_queue import (
    EscalationPersistenceError,
    get_escalation_view,
    list_pending,
    record_decision,
)

DEFAULT_BUSINESS_ID = "demo-cafe"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record a trusted AllerGuard owner choice.")
    parser.add_argument("--business-id", default=DEFAULT_BUSINESS_ID)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="show current pending escalations")
    for name in ("show", "approve", "decline"):
        command = commands.add_parser(name)
        command.add_argument("escalation_id")
    edit = commands.add_parser("edit")
    edit.add_argument("escalation_id")
    edit.add_argument("--pack-file", required=True)
    return parser


def _pack_lines(label: str, pack: ActionPack) -> list[str]:
    return [
        f"{label} pull: {pack.pull}",
        f"{label} staff note: {pack.staff_note}",
        f"{label} customer notice: {pack.customer_notice}",
        f"{label} substitution: {pack.substitution}",
    ]


def _notification_state(business_id: str, assessment_id: str, settings: Settings) -> str:
    entries = audit.list_audit_entries(business_id, settings)
    matches = [
        entry
        for entry in entries
        if entry.assessment_id == assessment_id
        and entry.event
        in {
            AuditEvent.NOTIFICATION_SENT,
            AuditEvent.NOTIFICATION_FAILED,
            AuditEvent.NOTIFICATION_UNKNOWN,
        }
    ]
    if not matches:
        return "none recorded"
    latest = matches[-1]
    return (
        f"{latest.event.value} ({latest.notification.outcome.value})"
        if latest.notification
        else latest.event.value
    )


def _show(business_id: str, escalation_id: str, settings: Settings) -> int:
    view = get_escalation_view(business_id, escalation_id, settings)
    if view is None:
        print("No escalation found for that business and ID.")
        return 2
    escalation = view.escalation
    print(f"Business: {business_id}")
    print(f"Escalation ID: {escalation.escalation_id}")
    print(f"Effective status: {view.effective_status.value}")
    print(f"Draft source: {escalation.draft_source.value} ({escalation.drafter_model_id})")
    print(f"Notification: {_notification_state(business_id, escalation.assessment_id, settings)}")
    print("Original draft:")
    for line in _pack_lines("  ", escalation.action_pack):
        print(line)
    if view.decision_record is not None:
        record = view.decision_record
        print(f"Stored owner decision: {record.decision.value} at {record.decided_at.isoformat()}")
        if record.edited_pack is not None:
            print("Edited draft:")
            for line in _pack_lines("  ", record.edited_pack):
                print(line)
    print("Recording a choice does not execute the action pack or send it to customers.")
    return 0


def _list(business_id: str, settings: Settings) -> int:
    pending = list_pending(business_id, settings)
    print(f"Pending escalations for {business_id}: {len(pending)}")
    for escalation in pending:
        print(
            f"{escalation.escalation_id} | {escalation.alert_title} | "
            f"{escalation.draft_source.value}"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run one read-only view or one first-write-wins owner command."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 1
    settings = Settings.from_environment()
    try:
        if args.command == "list":
            return _list(args.business_id, settings)
        if args.command == "show":
            return _show(args.business_id, args.escalation_id, settings)
        decision = {
            "approve": OwnerDecision.APPROVE,
            "decline": OwnerDecision.DECLINE,
            "edit": OwnerDecision.EDIT,
        }[args.command]
        edited_pack = load_action_pack(args.pack_file) if args.command == "edit" else None
        result = record_decision(
            args.business_id,
            args.escalation_id,
            decision,
            edited_pack,
            decided_at=datetime.now(UTC),
            settings=settings,
        )
        state = "recorded" if result.created else "already recorded; stored first choice retained"
        print(f"Owner decision {state}: {result.record.decision.value}")
        print(f"Escalation ID: {result.record.escalation_id}")
        print(f"Decision audit: {result.audit.entry.entry_id}")
        print("Recording a choice does not execute the action pack or send it to customers.")
        return 0
    except (
        DecisionInputError,
        ValueError,
        EscalationPersistenceError,
        audit.AuditPersistenceError,
    ) as error:
        print(f"Command failed: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
