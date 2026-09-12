"""Offline owner decision demo: simulated notification followed by owner choices."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from moto import mock_aws

from scripts.demo_gate_audit import _load_scenario_alerts, _offline_assessor, _offline_drafter
from src.config import Settings
from src.domain.demo_cafe import build_demo_profile
from src.domain.models import (
    Escalation,
    NotificationMode,
    NotificationOutcome,
    NotificationProvider,
    NotificationReceipt,
)
from src.runtime.approve import main as approve_main
from src.runtime.notification import DeliveryFunction
from src.runtime.process_alert import process_alert
from src.tools.audit import ensure_audit_table, list_audit_entries
from src.tools.audit_report import write_audit_report
from src.tools.escalation_queue import ensure_escalation_table, list_pending

OFFLINE_BANNER = (
    "OFFLINE DEMONSTRATION | SIMULATED NOTIFICATION | SIMULATED OWNER CHOICES | "
    "MOTO MEMORY STORE | NO AWS | NO BEDROCK"
)


def _simulated_notifier(calls: list[str]) -> DeliveryFunction:
    def notify(
        escalation: Escalation, settings: Settings, attempted_at: datetime
    ) -> NotificationReceipt:
        calls.append(escalation.escalation_id)
        return NotificationReceipt(
            business_id=escalation.business_id,
            escalation_id=escalation.escalation_id,
            outcome=NotificationOutcome.ACCEPTED,
            provider=NotificationProvider.STUB,
            mode=NotificationMode.SIMULATED,
            attempted_at=attempted_at,
            message_id=f"simulated-{escalation.escalation_id[:12]}",
        )

    return notify


def _edited_pack() -> dict[str, str]:
    return {
        "pull": "DRAFT: isolate the selected recall stock while the owner checks the details.",
        "staff_note": "DRAFT: keep potentially affected stock away from sale pending review.",
        "customer_notice": (
            "DRAFT ONLY — NOT SENT — AWAITING OWNER APPROVAL: proposed wording for "
            "the selected recall."
        ),
        "substitution": "No substitution suggested.",
    }


def run_demo(report: Path) -> int:
    """Run one serial, all-offline notification and owner-choice demonstration."""
    calls: list[str] = []
    profile = build_demo_profile()
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures"
    with (
        patch.dict(
            os.environ,
            {
                "AWS_ACCESS_KEY_ID": "testing",
                "AWS_SECRET_ACCESS_KEY": "testing",
                "AWS_SESSION_TOKEN": "testing",
                "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_REGION": "eu-west-2",
                "ALLERGUARD_DYNAMODB_TABLE_AUDIT": "allerguard-human-loop-audit",
                "ALLERGUARD_DYNAMODB_TABLE_ESCALATIONS": "allerguard-human-loop-escalations",
                "ALLERGUARD_NOTIFICATION_MODE": "ses",
                "ALLERGUARD_SES_FROM_EMAIL": "synthetic-owner@example.test",
                "ALLERGUARD_OWNER_EMAIL": "synthetic-owner@example.test",
            },
        ),
        mock_aws(),
    ):
        os.environ.pop("AWS_PROFILE", None)
        os.environ.pop("AWS_DEFAULT_PROFILE", None)
        os.environ.pop("ALLERGUARD_SNS_TOPIC_ARN", None)
        settings = Settings.from_environment().model_copy(
            update={
                "fsa_mode": "replay",
                "fsa_fixtures_path": fixture_root / "alerts_recent.json",
            }
        )
        ensure_audit_table(settings)
        ensure_escalation_table(settings)
        alerts = _load_scenario_alerts("full", settings)
        notifier = _simulated_notifier(calls)
        print(f"\nALLERGUARD | OWNER DECISION LOOP\n{OFFLINE_BANNER}\n{'=' * 78}")
        print("PHASE 1 — process five replay fixtures through match, gate, queue and audit.")
        for alert in alerts:
            process_alert(
                alert,
                profile,
                timestamp=datetime.now(UTC),
                settings=settings,
                assessor=_offline_assessor,
                drafter=_offline_drafter,
                notifier=notifier,
            )
        first_rows = list_audit_entries(profile.business_id, settings)
        first_pending = list_pending(profile.business_id, settings)
        print(
            f"Initial read-back: {len(first_rows)} audit events, "
            f"{len(first_pending)} pending, {len(calls)} simulated notifications."
        )
        print("PHASE 2 — serial replay; stored assessments and notifications are reused.")
        for alert in alerts:
            process_alert(
                alert,
                profile,
                timestamp=datetime.now(UTC),
                settings=settings,
                assessor=_offline_assessor,
                drafter=_offline_drafter,
                notifier=notifier,
            )
        replay_rows = list_audit_entries(profile.business_id, settings)
        print(
            f"Replay read-back: {len(replay_rows)} audit events, "
            f"{len(list_pending(profile.business_id, settings))} pending, "
            f"{len(calls)} simulated notifications total."
        )
        if len(first_rows) != 11 or len(first_pending) != 3 or len(calls) != 3:
            raise RuntimeError("Unexpected initial owner decision demo totals.")
        if len(replay_rows) != 11:
            raise RuntimeError("Replay changed persisted owner decision totals.")

        queued = list_pending(profile.business_id, settings)
        queued.sort(key=lambda item: item.escalation_id)
        print("PHASE 3 — simulate three explicit owner choices on three distinct IDs.")
        print("  approve:", queued[0].escalation_id)
        approve_main(["--business-id", profile.business_id, "approve", queued[0].escalation_id])
        with TemporaryDirectory() as directory:
            pack_path = Path(directory) / "edited-pack.json"
            pack_path.write_text(json.dumps(_edited_pack()), encoding="utf-8")
            print("  edit:", queued[1].escalation_id)
            approve_main(
                [
                    "--business-id",
                    profile.business_id,
                    "edit",
                    queued[1].escalation_id,
                    "--pack-file",
                    str(pack_path),
                ]
            )
        print("  decline:", queued[2].escalation_id)
        approve_main(["--business-id", profile.business_id, "decline", queued[2].escalation_id])

        decided_rows = list_audit_entries(profile.business_id, settings)
        if len(list_pending(profile.business_id, settings)) != 0 or len(decided_rows) != 14:
            raise RuntimeError("Owner choices did not produce the expected 3-to-0 transition.")
        print(
            f"Decision read-back: {len(decided_rows)} audit events, "
            f"{len(list_pending(profile.business_id, settings))} pending, 3 decisions."
        )
        print("PHASE 4 — replay after owner choices; no new sends or decisions.")
        for alert in alerts:
            process_alert(
                alert,
                profile,
                timestamp=datetime.now(UTC),
                settings=settings,
                assessor=_offline_assessor,
                drafter=_offline_drafter,
                notifier=notifier,
            )
        final_rows = list_audit_entries(profile.business_id, settings)
        print(
            f"Final read-back: {len(final_rows)} audit events, "
            f"{len(list_pending(profile.business_id, settings))} pending, "
            f"{len(calls)} simulated notifications total."
        )
        if len(final_rows) != 14 or len(calls) != 3:
            raise RuntimeError("Post-decision replay added unexpected events or sends.")
        report_path = write_audit_report(
            final_rows,
            report,
            storage_label="Offline Moto · simulated notification · simulated owner choices",
        )
        print(f"Evidence report: {report_path}")
        print("No live provider, customer action, stock action, watermark or supervisor ran.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("artifacts/human-loop.html"))
    return run_demo(parser.parse_args().report)


if __name__ == "__main__":
    raise SystemExit(main())
