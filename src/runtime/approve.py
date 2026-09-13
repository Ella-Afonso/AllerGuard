"""Trusted local owner commands for viewing and recording escalation choices."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from typing import Sequence

from src.config import Settings
from src.domain.diary import DailyStatus, DiaryConfirmation
from src.domain.models import ActionPack, AuditEvent, OwnerDecision
from src.tools import audit
from src.tools.decision_input import DecisionInputError, load_action_pack
from src.tools.diary import confirm_diary, read_diary_view
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
    diary = commands.add_parser("diary", help="view a daily record or confirm explicit answers")
    daily_commands = diary.add_subparsers(dest="diary_command", required=True)
    daily_show = daily_commands.add_parser("show")
    daily_show.add_argument("entry_date", type=date.fromisoformat)
    confirm = daily_commands.add_parser("confirm")
    confirm.add_argument("entry_date", type=date.fromisoformat)
    confirm.add_argument("--opening", choices=("confirmed", "exception"), required=True)
    confirm.add_argument("--closing", choices=("confirmed", "exception"), required=True)
    confirm.add_argument("--note", default="")
    confirm.add_argument("--simulated", action="store_true", help="label demonstration input")
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


def main(
    argv: Sequence[str] | None = None,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> int:
    """Run one read-only view or one first-write-wins owner command."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 1
    settings = settings or Settings.from_environment()
    now = now or datetime.now(UTC)
    try:
        if args.command == "diary":
            if args.diary_command == "show":
                view = read_diary_view(
                    args.business_id, args.entry_date, as_of=now, settings=settings
                )
                print(f"Diary: {view.filed.entry_id}")
                print("Original filing: opening unconfirmed; closing unconfirmed.")
                if view.confirmation is not None and view.confirmation.confirmation is not None:
                    answers = view.confirmation.confirmation
                    print(
                        f"Owner confirmation ({answers.mode}): opening "
                        f"{answers.opening_status.value}; closing {answers.closing_status.value}."
                    )
                    print(f"Note: {answers.note or 'None'}")
                else:
                    print("Opening and closing await explicit owner confirmation.")
                for link in view.current_recall_actions:
                    print(f"Recall: {link.alert_title} | {link.state} | {link.event_id}")
                print("Owner choices do not prove stock or customer actions were executed.")
                return 0
            daily_result = confirm_diary(
                args.business_id,
                args.entry_date,
                DiaryConfirmation(
                    opening_status=DailyStatus(args.opening),
                    closing_status=DailyStatus(args.closing),
                    note=args.note,
                    mode="simulated" if args.simulated else "owner",
                ),
                now=now,
                settings=settings,
            )
            print(
                f"Diary confirmation {'recorded' if daily_result.created else 'already recorded'}: "
                f"{daily_result.record.entry_id}"
            )
            print("Stored first answers retained. No customer or stock action executed.")
            return 0
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
            decided_at=now,
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
