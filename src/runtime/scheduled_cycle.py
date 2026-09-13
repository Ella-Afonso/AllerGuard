"""Lambda entry point for a serial, notification-disabled infrastructure proof."""

from __future__ import annotations

import logging
from typing import Any

from src.config import Settings
from src.domain.cycle import CycleStatus
from src.runtime.cycle import run_monitoring_cycle
from src.runtime.replay_proposals import assess_replay, draft_replay
from src.tools.inventory import read_business

logger = logging.getLogger(__name__)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Run configuration-owned work; never trust event-supplied table or model IDs.

    Reserve concurrency at one. Failed/uncertain batches raise so Lambda cannot
    report success. This proof intentionally performs no external notification.
    """
    settings = Settings.from_environment()
    if settings.notification_mode != "disabled":
        raise ValueError("Scheduled proof requires notifications disabled.")
    if settings.cycle_proposal_mode == "injected" and settings.fsa_mode != "replay":
        raise ValueError("Injected proposals require replay fixtures.")
    business = read_business(settings.cycle_business_id, settings)
    if business is None:
        raise ValueError("Configured synthetic business must be seeded before scheduling.")
    injected = settings.cycle_proposal_mode == "injected"
    report = run_monitoring_cycle(
        business,
        settings=settings,
        assessor=assess_replay if injected else None,
        drafter=draft_replay if injected else None,
    )
    logger.warning(
        "scheduled_cycle proposal_mode=%s notification_mode=disabled report=%s",
        settings.cycle_proposal_mode,
        report.model_dump_json(),
    )
    if report.status not in (CycleStatus.COMMITTED, CycleStatus.EMPTY):
        raise RuntimeError(f"Monitoring cycle incomplete: {report.status.value}")
    return {"proposal_mode": settings.cycle_proposal_mode, "cycle": report.model_dump(mode="json")}
