"""Paid model tests are opt-in; the default suite stays offline."""

from __future__ import annotations

import os

import pytest

from tests.audit_support import audit_settings  # noqa: F401 -- shared pytest fixture


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Do not contact Bedrock without the explicit test-run environment flag."""
    if os.environ.get("ALLERGUARD_LIVE_BEDROCK") == "1":
        return
    skip = pytest.mark.skip(reason="Set ALLERGUARD_LIVE_BEDROCK=1 to enable paid Bedrock tests.")
    for item in items:
        if item.get_closest_marker("live_bedrock"):
            item.add_marker(skip)
