"""Rebuild the public simulation snapshot from the canonical offline pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from src.domain.demo_cafe import build_demo_profile
from src.runtime.replay_proposals import assess_replay, draft_replay
from src.safety.gate import gate
from src.tools.fsa_api import parse_fsa_response


def build_snapshot(root: Path) -> dict[str, object]:
    business = build_demo_profile()
    rows: list[dict[str, object]] = []
    for name in (
        "nomatch_1",
        "nomatch_2",
        "match_confirmed",
        "allergen_nonstocked",
        "batch_unknown",
    ):
        payload = json.loads((root / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))
        alert = parse_fsa_response(payload)[0]
        match = assess_replay(alert, business)
        decision = gate(match)
        row: dict[str, object] = {
            "id": alert.id,
            "title": alert.title,
            "tier": match.tier.value,
            "decision": decision.value.upper(),
            "reason": match.reason,
            "alert_url": alert.alert_url,
            "modified": alert.modified.isoformat(),
        }
        if decision.value.upper() == "ESCALATE":
            row["action_pack"] = draft_replay(alert, business, match).model_dump(mode="json")
        rows.append(row)
    return {"business": business.model_dump(mode="json"), "alerts": rows}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (
        "// Generated from canonical Python fixtures and replay proposals. "
        "Browser simulation only.\n"
    )
    text += "const ALLERGUARD_DEMO_DATA = " + json.dumps(build_snapshot(root), indent=2) + ";\n"
    (root / "pages-demo" / "data.js").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
