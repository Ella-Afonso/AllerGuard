"""Readable Matcher evidence demonstration; offline unless --live is explicit."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from textwrap import fill

from src.agents.matcher import match_alert
from src.domain.demo_cafe import build_demo_profile
from src.domain.match_judgement import MatcherError
from src.domain.models import ConfidenceTier, MatcherProposal
from src.domain.tiers import deterministic_floor
from src.tools.fsa_api import parse_fsa_response

FIXTURE_NAMES = (
    "batch_unknown",
    "match_confirmed",
    "allergen_nonstocked",
    "nomatch_1",
    "nomatch_2",
)


def main() -> int:
    """Run one captured alert through the application Matcher without database writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", choices=FIXTURE_NAMES, default="batch_unknown")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Call Bedrock (uses AWS credits).")
    mode.add_argument("--inject-tier", choices=[t.value for t in ConfidenceTier])
    args = parser.parse_args()
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / f"{args.fixture}.json"
    payload: object = json.loads(fixture.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        parser.error("Fixture must be an FSA JSON object.")
    alert = parse_fsa_response(payload)[0]
    profile = build_demo_profile()
    floor = deterministic_floor(alert, profile)
    print("\nALLERGUARD | MATCHER EVIDENCE\n" + "=" * 64)
    print("LIVE BEDROCK" if args.live else "INJECTED-RESPONSE SAFEGUARD (offline)")
    print(f"Historical replay: {alert.id} | published {alert.created}")
    print(f"Source: {alert.alert_url or alert.id_uri}")
    print(fill("Recalled: " + ", ".join(alert.products), width=88))
    print(f"Business: {profile.name}")
    print(f"Deterministic floor: {floor.tier.value}\n")
    for candidate in floor.candidates:
        print(
            fill(
                f"{candidate.candidate_id} | {candidate.inventory_item_name or 'Business allergen'}"
                f" | {candidate.evidence}",
                width=88,
            )
        )
    proposal = None
    if not args.live:
        tier = ConfidenceTier(args.inject_tier) if args.inject_tier else floor.tier
        proposal = MatcherProposal(
            proposed_tier=tier,
            reason="This is unrelated." if tier is ConfidenceTier.NO_MATCH else floor.reason,
            evidence_refs=[c.candidate_id for c in floor.candidates],
        )
        print(f"\nInjected proposal: {tier.value}")
    else:
        # The production Matcher logs proposal/final ranks; do not re-invoke it for display.
        logging.basicConfig(level=logging.WARNING, format="%(message)s")
        logging.getLogger("src.agents.matcher").setLevel(logging.INFO)
    try:
        result = match_alert(alert, profile, injected_proposal=proposal)
    except MatcherError as error:
        print(f"\nASSESSMENT REJECTED | {type(error).__name__}\n{error}")
        print(
            "No successful match result. Use the alert-processing runtime for human-review routing."
        )
        return 1
    print(f"\nFinal assessment: {result.tier.value}")
    if proposal and result.tier != proposal.proposed_tier:
        print("Safeguard: model downgrade blocked; application explanation used.")
    print("\n" + fill(result.reason, width=88))
    print("\nMatching only: no notification, approval or audit write performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
