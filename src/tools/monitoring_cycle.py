"""A fixed-business cycle capability with no model-supplied batch controls."""

from strands import tool
from strands.tools.decorator import DecoratedFunctionTool

from src.config import Settings
from src.domain.models import BusinessProfile
from src.runtime.cycle import run_monitoring_cycle


def build_cycle_tool(
    business: BusinessProfile, settings: Settings
) -> DecoratedFunctionTool[[], str]:
    """Bind trusted configuration before exposing the no-argument capability."""
    configured_business = business.model_copy(deep=True)
    configured_settings = settings.model_copy(deep=True)

    @tool
    def run_cycle() -> str:
        """Run the complete configured monitoring cycle and return its evidence JSON.

        The runtime owns retrieval, ordering, audit and commit eligibility. A
        blocked or uncertain status is not success. This does not approve actions.
        """
        return run_monitoring_cycle(
            configured_business, settings=configured_settings
        ).model_dump_json()

    return run_cycle
