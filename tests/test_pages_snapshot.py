"""Public snapshot must keep the canonical business and safety outcomes."""

import json
from pathlib import Path

from scripts.build_pages_data import build_snapshot


def test_public_snapshot_matches_canonical_pipeline() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "pages-demo" / "data.js").read_text(encoding="utf-8")
    actual = json.loads(source.split(" = ", 1)[1].strip().removesuffix(";"))
    assert actual == build_snapshot(root)
    assert [a["tier"] for a in actual["alerts"]] == [
        "NO_MATCH",
        "NO_MATCH",
        "POSSIBLE",
        "POSSIBLE",
        "LIKELY",
    ]
