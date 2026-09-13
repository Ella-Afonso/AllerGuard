"""Offline daily diary and unified evidence proof using the shared runtime."""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from moto import mock_aws

from scripts.demo_cycle import _settings
from scripts.demo_gate_audit import SCENARIOS, _offline_assessor, _offline_drafter
from scripts.demo_human_loop import _edited_pack, _simulated_notifier
from src.domain.demo_cafe import build_demo_profile
from src.domain.diary import DiaryEvent, DiaryRecord
from src.runtime.approve import main as approve_main
from src.runtime.cycle import run_monitoring_cycle
from src.runtime.daily_diary import run_daily_diary
from src.tools import alert_ledger, audit
from src.tools.diary import read_diary_view
from src.tools.escalation_queue import ensure_escalation_table, list_pending
from src.tools.export import export_evidence

DORITOS_ID = "FSA-AA-38-2026"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run_demo(
    entry_date: date, owner_confirmation: str, report: Path, csv_path: Path, trace: Path
) -> int:
    """One isolated Moto lifetime; every displayed success is checked."""
    for output in (report, csv_path, trace):
        output.parent.mkdir(parents=True, exist_ok=True)
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures"
    items: list[dict[str, object]] = []
    for name in SCENARIOS["full"]:
        items.extend(
            json.loads((fixture_root / f"{name}.json").read_text(encoding="utf-8"))["items"]
        )
    fixture = trace.parent / "diary-fixtures.json"
    fixture.write_text(json.dumps({"items": items}), encoding="utf-8")
    settings = _settings(fixture)
    profile = build_demo_profile()
    started = datetime.combine(entry_date, time(12), ZoneInfo("Europe/London")).astimezone(UTC)
    filed_at = started + timedelta(hours=1)
    confirmed_at = filed_at + timedelta(minutes=1)
    calls: list[str] = []
    env = {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_REGION": "eu-west-2",
    }
    with patch.dict(os.environ, env):
        for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "ALLERGUARD_SNS_TOPIC_ARN"):
            os.environ.pop(name, None)
        with mock_aws():
            audit.ensure_audit_table(settings)
            ensure_escalation_table(settings)
            alert_ledger.ensure_alerts_seen_table(settings)
            print("ALLERGUARD | DAILY DIARY AND EVIDENCE")
            print("OFFLINE MOTO | SIMULATED RECALL CHOICES | NO AWS | NO BEDROCK")
            # Freeze only the runtime clock; assessment and storage use the real shared code.
            with patch("src.runtime.cycle.datetime", wraps=datetime) as cycle_time:
                cycle_time.now.return_value = started
                cycle = run_monitoring_cycle(
                    profile,
                    settings=settings,
                    assessor=_offline_assessor,
                    drafter=_offline_drafter,
                    notifier=_simulated_notifier(calls),
                )
            require(cycle.status.value == "committed", "Monitoring cycle did not commit.")
            require(
                (cycle.retrieved, cycle.silent, cycle.escalated) == (5, 2, 3),
                "Unexpected cycle evidence.",
            )
            queued = list_pending(profile.business_id, settings)
            require(any(row.alert_id == DORITOS_ID for row in queued), "Doritos queue missing.")
            edited_path = trace.parent / "diary-edited-pack.json"
            edited_path.write_text(json.dumps(_edited_pack()), encoding="utf-8")
            for row in queued:
                choice = (
                    "approve"
                    if row.alert_id == DORITOS_ID
                    else ("edit" if row.alert_id == "FSA-AA-42-2026" else "decline")
                )
                args = ["--business-id", profile.business_id, choice, row.escalation_id]
                if choice == "edit":
                    args += ["--pack-file", str(edited_path)]
                require(
                    approve_main(args, now=started + timedelta(minutes=30), settings=settings) == 0,
                    "Owner choice failed.",
                )
            filed = run_daily_diary(
                profile.business_id, entry_date, now=filed_at, settings=settings
            )
            require(filed.created, "Initial filing was not created.")
            show = ["--business-id", profile.business_id, "diary", "show", str(entry_date)]
            require(approve_main(show, now=filed_at, settings=settings) == 0, "Diary view failed.")
            confirm = [
                "--business-id",
                profile.business_id,
                "diary",
                "confirm",
                str(entry_date),
                "--opening",
                "confirmed",
                "--closing",
                "confirmed",
                "--simulated",
            ]
            if owner_confirmation == "simulated":
                require(
                    approve_main(confirm, now=confirmed_at, settings=settings) == 0,
                    "Diary confirmation failed.",
                )
            before = audit.list_history(profile.business_id, settings)
            replay = run_daily_diary(
                profile.business_id, entry_date, now=confirmed_at, settings=settings
            )
            require(
                not replay.created and replay.record == filed.record, "Filing changed on retry."
            )
            if owner_confirmation == "simulated":
                require(
                    approve_main(confirm, now=confirmed_at, settings=settings) == 0,
                    "Confirmation retry failed.",
                )
            after = audit.list_history(profile.business_id, settings)
            require(before == after, "Replay modified stored evidence.")
            view = read_diary_view(
                profile.business_id, entry_date, as_of=confirmed_at, settings=settings
            )
            approved = [
                link.alert_id for link in view.current_recall_actions if link.state == "approve"
            ]
            require(DORITOS_ID in approved, "Diary is missing the Doritos approval.")
            exported = export_evidence(
                profile.business_id,
                csv_path=csv_path,
                html_path=report,
                settings=settings,
                as_of=confirmed_at,
                storage_label=(
                    "Offline Moto · simulated recall choices · diary confirmation: "
                    f"{owner_confirmation}"
                ),
            )
            with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                csv_count = len(list(csv.DictReader(stream)))
            require(csv_count == exported.event_count == len(after), "Export is incomplete.")
            require(
                audit.list_history(profile.business_id, settings) == after, "Export changed data."
            )
            diary_rows = [row for row in after if isinstance(row, DiaryRecord)]
            evidence = {
                "offline": True,
                "business_id": profile.business_id,
                "entry_date": str(entry_date),
                "diary_filed_events": sum(row.event is DiaryEvent.FILED for row in diary_rows),
                "diary_confirmation_events": sum(
                    row.event is DiaryEvent.CONFIRMED for row in diary_rows
                ),
                "linked_approval_alert_ids": approved,
                "simulated_notifications": len(calls),
                "pending_escalations": len(list_pending(profile.business_id, settings)),
                "stored_events_before_replay": len(before),
                "stored_events_after_replay": len(after),
                "csv_rows": csv_count,
                "export_event_count": exported.event_count,
                "replay_unchanged": before == after,
            }
            trace.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print("Diary reused. Stored event count unchanged.")
            print(f"EXPORT | {exported.event_count} stored events | {exported.html_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--owner-confirmation", choices=("none", "simulated"), default="none")
    parser.add_argument("--report", type=Path, default=Path("artifacts/diary.html"))
    parser.add_argument("--csv", type=Path, default=Path("artifacts/diary.csv"))
    parser.add_argument("--trace", type=Path, default=Path("artifacts/diary-trace.json"))
    args = parser.parse_args()
    try:
        return run_demo(args.date, args.owner_confirmation, args.report, args.csv, args.trace)
    except Exception as error:
        print(f"Diary proof failed: {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
