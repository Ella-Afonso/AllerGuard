"""Run real match/gate/audit code: offline Moto by default, AWS only with --live."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path
from textwrap import fill
from unittest.mock import patch

from src.agents.matcher import match_alert
from src.config import Settings
from src.domain.demo_cafe import build_demo_profile
from src.domain.match_judgement import MatcherModelError
from src.domain.models import (
    Alert,
    AuditEntry,
    AuditEvent,
    BusinessProfile,
    MatcherProposal,
    MatchResult,
)
from src.domain.tiers import deterministic_floor
from src.runtime.process_alert import AssessmentFunction, process_alert
from src.tools.audit import AuditPersistenceError, ensure_audit_table, list_audit_entries
from src.tools.audit_report import AuditReportSummary, summarize_audit_entries, write_audit_report
from src.tools.fsa_api import load_alerts

SCENARIOS = {
    "headline": ("nomatch_1", "nomatch_2", "batch_unknown"),
    "full": ("nomatch_1", "nomatch_2", "match_confirmed", "allergen_nonstocked", "batch_unknown"),
    "failure": ("batch_unknown",),
}

OFFLINE_BANNER = (
    "OFFLINE DEMONSTRATION | INJECTED PROPOSALS | MOTO MEMORY STORE | NO AWS | NO BEDROCK"
)


def _offline_assessor(alert: Alert, business: BusinessProfile) -> MatchResult:
    """Inject a proposal through the real Matcher validation and finalisation path."""
    floor = deterministic_floor(alert, business)
    return match_alert(
        alert,
        business,
        injected_proposal=MatcherProposal(
            proposed_tier=floor.tier,
            reason=floor.reason,
            evidence_refs=[candidate.candidate_id for candidate in floor.candidates],
        ),
    )


def _failed_assessor(alert: Alert, business: BusinessProfile) -> MatchResult:
    raise MatcherModelError("Explicitly simulated provider failure for the offline demonstration.")


def _load_scenario_alerts(scenario: str, settings: Settings) -> list[Alert]:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    alerts: list[Alert] = []
    for fixture in SCENARIOS[scenario]:
        replay_settings = settings.model_copy(
            update={
                "fsa_mode": "replay",
                "fsa_fixtures_path": fixtures / f"{fixture}.json",
            }
        )
        alerts.extend(load_alerts(replay_settings))
    return alerts


def _print_persisted_summary(rows: list[AuditEntry], heading: str) -> AuditReportSummary:
    """Counts come from rows read back through the audit tool, not from local expectations."""
    summary = summarize_audit_entries(rows)
    print(heading)
    print(f"  stored audit events:              {summary.audit_events}")
    print(f"  distinct assessments:             {summary.distinct_assessments}")
    print(f"  silent decision events:             {summary.silent_decision_events}")
    print(f"  requires-review decision events:    {summary.escalation_decision_events}")
    print(f"  assessment error events:            {summary.error_events}")
    return summary


def run_demo(
    settings: Settings,
    *,
    scenario: str,
    live: bool,
    repeat: int,
    report: Path,
) -> int:
    """Read fixtures through the shared FSA loader and display persisted outcomes."""
    profile = build_demo_profile()
    alerts = _load_scenario_alerts(scenario, settings)
    label = "LIVE BEDROCK + AWS DYNAMODB" if live else OFFLINE_BANNER
    print(f"\nALLERGUARD | AUDITABLE DECISIONS\n{label}\n{'=' * 78}")
    print(f"Business: {profile.name}")
    print(f"Historical FSA replay fixtures | scenario: {scenario}")
    print("Uses process_alert -> real matcher validation, deterministic gate, audit append.")
    any_failure = False
    pass_summaries: list[AuditReportSummary] = []
    for run in range(repeat):
        print(f"\nPASS {run + 1}")
        for alert in alerts:
            assessor: AssessmentFunction | None = None if live else _offline_assessor
            if scenario == "failure" and run == 0:
                assessor = _failed_assessor
            try:
                outcome = process_alert(
                    alert,
                    profile,
                    timestamp=datetime.now(UTC),
                    settings=settings,
                    assessor=assessor,
                )
            except AuditPersistenceError:
                any_failure = True
                print(f"AUDIT UNAVAILABLE | {alert.id} | requires review; NOT acknowledged")
                continue
            entry = outcome.audit.entry
            action = "REUSED" if outcome.reused else "APPENDED"
            tier = entry.tier.value if entry.tier else "UNASSESSED"
            match_tier = (
                outcome.match_result.tier.value if outcome.match_result is not None else "NONE"
            )
            print(
                f"{action:8} | {outcome.decision.value.upper():8} | "
                f"{tier:10} | match={match_tier:10} | {alert.id}"
            )
            print(fill(entry.reason, width=94, initial_indent="  ", subsequent_indent="  "))
            if entry.event is AuditEvent.MATCH_ERROR and scenario != "failure":
                any_failure = True

        rows = list_audit_entries(profile.business_id, settings)
        pass_summaries.append(_print_persisted_summary(rows, f"\nREAD BACK AFTER PASS {run + 1}"))

    if scenario == "full" and len(pass_summaries) >= 2:
        first, second = pass_summaries[0], pass_summaries[1]
        if first == second:
            print("\nPASS 2 added no duplicate stored events (totals unchanged).")
        else:
            any_failure = True
            print("\nPASS 2 changed persisted totals — expected identical counts on reuse.")

    if scenario == "failure" and len(pass_summaries) >= 2:
        rows = list_audit_entries(profile.business_id, settings)
        if len(rows) >= 2:
            error_row = next(row for row in rows if row.event is AuditEvent.MATCH_ERROR)
            decision_row = next(row for row in rows if row.event is AuditEvent.MATCH_DECISION)
            print(
                "\nFAILURE + RECOVERY: two stored events share one assessment identity; "
                "the historical error row remains after recovery."
            )
            print(f"  error event:    {error_row.entry_id}")
            print(f"  decision event: {decision_row.entry_id}")
            print(f"  assessment_id:  {error_row.assessment_id}")
            assert error_row.assessment_id == decision_row.assessment_id

    rows = list_audit_entries(profile.business_id, settings)
    storage_label = (
        f"AWS DynamoDB · {settings.dynamodb_table_audit} · {settings.aws_region} · real Bedrock"
        if live
        else "Offline demonstration · Moto memory store · injected proposals · no AWS calls"
    )
    saved = write_audit_report(rows, report, storage_label=storage_label)
    print(f"\nEvidence report: {saved}")
    print("Matching, gate, audit only. No notification, approval, or watermark commit performed.")
    return 1 if any_failure else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="full")
    parser.add_argument(
        "--live", action="store_true", help="Uses real Bedrock and writes DynamoDB."
    )
    parser.add_argument(
        "--create-table", action="store_true", help="Explicitly provision audit table."
    )
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--report", type=Path, default=Path("artifacts/audit-demo.html"))
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    if args.scenario == "failure" and (args.live or args.repeat < 2):
        parser.error("failure is an offline simulation; use --repeat 2 or more")
    if args.live:
        settings = Settings.from_environment()
        if args.create_table:
            ensure_audit_table(settings)
        return run_demo(
            settings, scenario=args.scenario, live=True, repeat=args.repeat, report=args.report
        )
    from moto import mock_aws

    with patch.dict(
        os.environ,
        {
            "AWS_ACCESS_KEY_ID": "testing",
            "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_SESSION_TOKEN": "testing",
            "AWS_EC2_METADATA_DISABLED": "true",
        },
    ):
        os.environ.pop("AWS_PROFILE", None)
        os.environ.pop("AWS_DEFAULT_PROFILE", None)
        with mock_aws():
            settings = Settings.from_environment()
            ensure_audit_table(settings)
            return run_demo(
                settings, scenario=args.scenario, live=False, repeat=args.repeat, report=args.report
            )


if __name__ == "__main__":
    raise SystemExit(main())
