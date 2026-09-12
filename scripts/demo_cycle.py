"""Offline two-cycle proof for the unattended AllerGuard monitoring loop."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from moto import mock_aws

from scripts.demo_gate_audit import SCENARIOS, _offline_assessor, _offline_drafter
from scripts.demo_human_loop import _edited_pack, _simulated_notifier
from src.config import Settings
from src.domain.demo_cafe import build_demo_profile
from src.runtime.approve import main as approve_main
from src.runtime.cycle import run_monitoring_cycle
from src.tools import alert_ledger
from src.tools.audit import ensure_audit_table, list_audit_entries
from src.tools.audit_report import write_audit_report
from src.tools.escalation_queue import ensure_escalation_table, list_pending

SCENARIO = "full"


def _settings(fixture_path: Path) -> Settings:
    return Settings(
        aws_region="eu-west-2",
        bedrock_model_id="offline-cycle-model",
        fsa_mode="replay",
        fsa_fixtures_path=fixture_path,
        dynamodb_table_alerts_seen="cycle-alerts-seen",
        dynamodb_table_audit="cycle-audit",
        dynamodb_table_escalations="cycle-escalations",
        notification_mode="ses",
        ses_from_email="owner@example.test",
        owner_email="owner@example.test",
    )


def run_demo(report: Path, trace: Path, owner_choices: str) -> int:
    profile = build_demo_profile()
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures"
    # Build one replay feed before polling; the ledger still performs retrieval and deduplication.
    payload_items: list[dict[str, object]] = []
    for fixture_name in SCENARIOS[SCENARIO]:
        raw = json.loads((fixture_root / f"{fixture_name}.json").read_text(encoding="utf-8"))
        payload_items.extend(raw["items"])
    fixture = trace.parent / "cycle-fixtures.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps({"items": payload_items}), encoding="utf-8")
    settings = _settings(fixture)
    calls: list[str] = []
    started = datetime.now(UTC)
    with (
        patch.dict(
            os.environ,
            {
                "AWS_ACCESS_KEY_ID": "testing",
                "AWS_SECRET_ACCESS_KEY": "testing",
                "AWS_SESSION_TOKEN": "testing",
                "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_REGION": "eu-west-2",
                "ALLERGUARD_DYNAMODB_TABLE_AUDIT": settings.dynamodb_table_audit,
                "ALLERGUARD_DYNAMODB_TABLE_ESCALATIONS": settings.dynamodb_table_escalations,
            },
            clear=False,
        ),
        mock_aws(),
    ):
        os.environ.pop("AWS_PROFILE", None)
        os.environ.pop("AWS_DEFAULT_PROFILE", None)
        os.environ.pop("ALLERGUARD_SNS_TOPIC_ARN", None)
        ensure_audit_table(settings)
        ensure_escalation_table(settings)
        alert_ledger.ensure_alerts_seen_table(settings)
        print("\nALLERGUARD | AUTONOMOUS MONITORING CYCLE")
        print("OFFLINE DEMONSTRATION | MOTO MEMORY STORE | NO AWS | NO BEDROCK")
        first = run_monitoring_cycle(
            profile,
            settings=settings,
            assessor=_offline_assessor,
            drafter=_offline_drafter,
            notifier=_simulated_notifier(calls),
        )
        print(
            f"CYCLE 1 | {first.retrieved} alerts assessed - "
            f"{first.silent} handled silently, {first.escalated} escalated to you | "
            f"{first.status.value}"
        )
        second = run_monitoring_cycle(
            profile,
            settings=settings,
            assessor=_offline_assessor,
            drafter=_offline_drafter,
            notifier=_simulated_notifier(calls),
        )
        print(
            f"CYCLE 2 | {second.retrieved} new alerts - "
            f"nothing new needs you | {second.status.value}"
        )
        if owner_choices == "simulated":
            pending = sorted(
                list_pending(profile.business_id, settings), key=lambda row: row.escalation_id
            )
            approve_main(
                ["--business-id", profile.business_id, "approve", pending[0].escalation_id]
            )
            edited = trace.parent / "cycle-edited-pack.json"
            edited.write_text(json.dumps(_edited_pack()), encoding="utf-8")
            approve_main(
                [
                    "--business-id",
                    profile.business_id,
                    "edit",
                    pending[1].escalation_id,
                    "--pack-file",
                    str(edited),
                ]
            )
            approve_main(
                ["--business-id", profile.business_id, "decline", pending[2].escalation_id]
            )
            print("OWNER CHOICES | approve, edit and decline recorded")
        rows = list_audit_entries(profile.business_id, settings)
        report_path = write_audit_report(
            rows,
            report,
            storage_label="Offline Moto · deterministic cycle · simulated notifications",
        )
        final = run_monitoring_cycle(
            profile,
            settings=settings,
            assessor=_offline_assessor,
            drafter=_offline_drafter,
            notifier=_simulated_notifier(calls),
        )
        trace.write_text(
            json.dumps(
                {
                    "started_at": started.isoformat(),
                    "finished_at": datetime.now(UTC).isoformat(),
                    "process_id": os.getpid(),
                    "offline": True,
                    "owner_choices": owner_choices,
                    "reports": [
                        first.model_dump(mode="json"),
                        second.model_dump(mode="json"),
                        final.model_dump(mode="json"),
                    ],
                    "audit_events": len(rows),
                    "pending": len(list_pending(profile.business_id, settings)),
                    "simulated_notifications": len(calls),
                    "report": str(report_path),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"EVIDENCE | {report_path}")
        print(f"TRACE | {trace}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("artifacts/cycle.html"))
    parser.add_argument("--trace", type=Path, default=Path("artifacts/cycle-trace.json"))
    parser.add_argument("--owner-choices", choices=("none", "simulated"), default="none")
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.trace.parent.mkdir(parents=True, exist_ok=True)
    return run_demo(args.report, args.trace, args.owner_choices)


if __name__ == "__main__":
    raise SystemExit(main())
