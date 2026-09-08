"""Small local tools used by AllerGuard agents."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from strands import tool

logger = logging.getLogger(__name__)


@tool
def get_current_utc_time() -> str:
    """Return the current UTC timestamp in ISO 8601 format.

    Use this tool when a response needs the current time. It has no external
    service dependency and is safe to call during the local Hello-agent demo.
    """
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    logger.info("Tool called: get_current_utc_time; utc_timestamp=%s", timestamp)
    return timestamp
