"""Seed the fictional AllerGuard demo café into DynamoDB."""

from __future__ import annotations

from src.config import Settings
from src.domain.demo_cafe import build_demo_profile
from src.tools.inventory import ensure_business_table, seed_business


def main() -> None:
    """Create the table if needed and seed the fictional café."""
    settings = Settings.from_environment()
    profile = build_demo_profile()

    ensure_business_table(settings)
    seed_business(profile)

    print(f"Seeded business '{profile.business_id}' into '{settings.dynamodb_table_businesses}'.")


if __name__ == "__main__":
    main()
