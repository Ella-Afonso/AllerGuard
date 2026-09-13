"""Bounded replay inputs and temporary evidence downloads."""

import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from src.config import Settings
from src.tools.export import export_evidence

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ("nomatch_1", "nomatch_2", "match_confirmed", "allergen_nonstocked", "batch_unknown")


def write_replay_feed(output: Path) -> Path:
    items: list[dict[str, object]] = []
    for name in SCENARIOS:
        payload = json.loads((ROOT / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))
        items.extend(payload["items"])
    output.write_text(json.dumps({"items": items}), encoding="utf-8")
    return output


def download_evidence(
    business_id: str,
    settings: Settings,
    kind: Literal["csv", "html"],
    *,
    now: datetime,
    label: str,
) -> bytes:
    with TemporaryDirectory(prefix="allerguard-export-") as folder:
        root = Path(folder)
        result = export_evidence(
            business_id,
            csv_path=root / "evidence.csv",
            html_path=root / "evidence.html",
            settings=settings,
            as_of=now,
            storage_label=label,
        )
        return (result.csv_path if kind == "csv" else result.html_path).read_bytes()
