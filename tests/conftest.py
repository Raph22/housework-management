"""Shared Home Assistant fixtures for Housework regression tests."""

import pytest

# Import before HA mounts its fixture config directory, which has another package.
import custom_components


@pytest.fixture(autouse=True)
def enable_housework_custom_integration(enable_custom_integrations):
    """Allow Home Assistant to load the integration from this repository."""
    yield custom_components
