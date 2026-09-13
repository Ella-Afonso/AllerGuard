"""Thin surface adapter over existing monitoring, queue, diary and export operations."""

from datetime import UTC, datetime
from typing import Literal

from src.domain.diary import DiaryConfirmation, DiaryView, business_date, diary_id
from src.domain.models import ActionPack, DecisionAppendResult, OwnerDecision
from src.runtime.cycle import run_monitoring_cycle
from src.runtime.daily_diary import run_daily_diary
from src.runtime.replay_proposals import assess_replay, draft_replay
from src.tools import audit
from src.tools.demo_sessions import SurfaceSession, simulated_notification
from src.tools.diary import confirm_diary, read_diary_view
from src.tools.escalation_queue import record_decision
from src.tools.surface_files import download_evidence


def cycle(session: SurfaceSession) -> None:
    session.last_cycle = run_monitoring_cycle(
        session.business,
        settings=session.settings,
        assessor=assess_replay,
        drafter=draft_replay,
        notifier=simulated_notification,
    )


def decide(
    session: SurfaceSession,
    identity: str,
    choice: OwnerDecision,
    pack: ActionPack | None,
) -> DecisionAppendResult:
    return record_decision(
        session.business.business_id,
        identity,
        choice,
        pack,
        decided_at=datetime.now(UTC),
        settings=session.settings,
    )


def diary(session: SurfaceSession) -> DiaryView | None:
    now = datetime.now(UTC)
    day = business_date(now)
    if (
        audit.get_diary_record(session.business.business_id, diary_id(day), session.settings)
        is None
    ):
        return None
    return read_diary_view(
        session.business.business_id,
        day,
        as_of=now,
        settings=session.settings,
    )


def file_diary(session: SurfaceSession) -> None:
    now = datetime.now(UTC)
    run_daily_diary(
        session.business.business_id,
        business_date(now),
        now=now,
        settings=session.settings,
    )


def confirm(session: SurfaceSession, answers: DiaryConfirmation) -> bool:
    now = datetime.now(UTC)
    receipt = confirm_diary(
        session.business.business_id,
        business_date(now),
        answers.model_copy(update={"mode": "simulated"}),
        now=now,
        settings=session.settings,
    )
    return receipt.created


def export(session: SurfaceSession, kind: Literal["csv", "html"], label: str) -> bytes:
    return download_evidence(
        session.business.business_id,
        session.settings,
        kind,
        now=datetime.now(UTC),
        label=label,
    )
