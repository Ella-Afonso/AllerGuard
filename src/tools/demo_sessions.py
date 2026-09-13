"""Process-lifetime mock storage with independent, bounded demonstration ledgers."""

from __future__ import annotations

import os
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from threading import RLock
from unittest.mock import patch
from uuid import uuid4

from src.config import Settings
from src.domain.cycle import CycleReport
from src.domain.demo_cafe import build_demo_profile
from src.domain.models import (
    BusinessProfile,
    Escalation,
    NotificationMode,
    NotificationOutcome,
    NotificationProvider,
    NotificationReceipt,
)
from src.tools import alert_ledger, audit, inventory
from src.tools.escalation_queue import ensure_escalation_table
from src.tools.surface_files import write_replay_feed


@dataclass
class SurfaceSession:
    settings: Settings
    business: BusinessProfile
    csrf: str = field(default_factory=lambda: token_urlsafe(32))
    lock: RLock = field(default_factory=RLock)
    last_cycle: CycleReport | None = None


def simulated_notification(
    escalation: Escalation,
    settings: Settings,
    attempted_at: datetime,
) -> NotificationReceipt:
    return NotificationReceipt(
        business_id=escalation.business_id,
        escalation_id=escalation.escalation_id,
        outcome=NotificationOutcome.ACCEPTED,
        provider=NotificationProvider.STUB,
        mode=NotificationMode.SIMULATED,
        attempted_at=attempted_at,
        message_id=f"simulated-{escalation.escalation_id[:12]}",
    )


class DemoSessions:
    """One process only. No eviction/deletion; restart explicitly loses mock history."""

    def __init__(self, limit: int = 24) -> None:
        self.limit = limit
        self.sessions: dict[str, SurfaceSession] = {}
        self.lock = RLock()
        self.stack = ExitStack()
        self.feed: Path | None = None

    def start(self) -> None:
        from moto import mock_aws

        try:
            self.stack.enter_context(
                patch.dict(
                    os.environ,
                    {
                        "AWS_ACCESS_KEY_ID": "testing",
                        "AWS_SECRET_ACCESS_KEY": "testing",
                        "AWS_SESSION_TOKEN": "testing",
                        "AWS_EC2_METADATA_DISABLED": "true",
                    },
                )
            )
            for key in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
                os.environ.pop(key, None)
            self.stack.enter_context(mock_aws())
            folder = self.stack.enter_context(TemporaryDirectory(prefix="allerguard-demo-"))
            self.feed = write_replay_feed(Path(folder) / "replay.json")
        except Exception:
            self.stack.close()
            raise

    def close(self) -> None:
        self.sessions.clear()
        self.stack.close()
        self.feed = None

    def get(self, identity: str | None) -> SurfaceSession | None:
        with self.lock:
            return self.sessions.get(identity or "")

    def create(self) -> tuple[str, SurfaceSession]:
        with self.lock:
            if self.feed is None:
                raise RuntimeError("Demonstration storage has not started.")
            if len(self.sessions) >= self.limit:
                raise RuntimeError("Demo capacity reached; existing sessions remain available.")
            prefix = f"demo-{uuid4().hex}"
            settings = Settings(
                aws_region="eu-west-2",
                bedrock_model_id="injected-replay",
                fsa_mode="replay",
                fsa_fixtures_path=self.feed,
                notification_mode="ses",
                owner_email="owner@example.test",
                ses_from_email="owner@example.test",
                dynamodb_table_businesses=prefix + "-business",
                dynamodb_table_alerts_seen=prefix + "-ledger",
                dynamodb_table_audit=prefix + "-audit",
                dynamodb_table_escalations=prefix + "-queue",
            )
            inventory.ensure_business_table(settings)
            audit.ensure_audit_table(settings)
            ensure_escalation_table(settings)
            alert_ledger.ensure_alerts_seen_table(settings)
            business = build_demo_profile()
            inventory.write_business(business, settings)
            session = SurfaceSession(settings, business)
            identity = token_urlsafe(32)
            self.sessions[identity] = session
            return identity, session
