"""Local runtime entry point for the AllerGuard Hello agent."""

from __future__ import annotations

import logging

from src.agents.hello import build_hello_agent
from src.config import Settings

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure readable console logs for the local demonstration."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> None:
    """Run the local AllerGuard Hello-agent readiness check."""
    configure_logging()

    settings = Settings.from_environment()
    logger.info(
        "Starting AllerGuard local Hello-agent run; region=%s; model_id=%s",
        settings.aws_region,
        settings.bedrock_model_id,
    )

    agent = build_hello_agent(settings)
    result = agent("Run the AllerGuard readiness check now. Call the time tool before replying.")

    logger.info("AllerGuard response: %s", str(result).strip())


if __name__ == "__main__":
    main()
