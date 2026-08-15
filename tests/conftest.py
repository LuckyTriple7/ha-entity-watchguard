"""Shared fixtures for Entity Watchguard tests."""
from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.entity_watchguard.const import (
    CONF_CHECK_INTERVAL,
    CONF_GRACE_PERIOD,
    CONF_MONITORED_DOMAINS,
    CONF_NOTIFY_ENABLED,
    CONF_REPAIRS_ENABLED,
    CONF_STAGE1_ENABLED,
    CONF_STAGE2_ENABLED,
    CONF_STARTUP_DELAY,
    DOMAIN,
)
from custom_components.entity_watchguard.coordinator import WatchguardCoordinator

# Tests drive the coordinator by hand, so everything that would otherwise wait
# for wall-clock time is off by default; each test opts back in explicitly.
BASE_OPTIONS = {
    CONF_STARTUP_DELAY: 0,
    CONF_GRACE_PERIOD: 0,
    CONF_CHECK_INTERVAL: 60,
    CONF_STAGE1_ENABLED: False,
    CONF_STAGE2_ENABLED: False,
    CONF_NOTIFY_ENABLED: False,
    CONF_REPAIRS_ENABLED: False,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def make_entry(hass):
    """Create (and register) a config entry with sensible test defaults."""

    def _make(domains: list[str] | None = None, **options) -> MockConfigEntry:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Entity Watchguard",
            data={CONF_MONITORED_DOMAINS: domains or ["light", "switch"]},
            options={**BASE_OPTIONS, **options},
        )
        entry.add_to_hass(hass)
        return entry

    return _make


@pytest.fixture
def setup_watchguard(hass, make_entry):
    """Set up the integration and hand back (entry, coordinator)."""

    async def _setup(domains: list[str] | None = None, **options):
        entry = make_entry(domains, **options)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry, hass.data[DOMAIN][entry.entry_id]

    return _setup


def backdate(coordinator: WatchguardCoordinator, seconds: int) -> None:
    """Pretend `seconds` have passed for every tracked entity.

    Shifts the recovery timestamps too, so retry intervals become due the same
    way they would with real time passing.
    """
    delta = timedelta(seconds=seconds)
    for tracked in coordinator.tracked.values():
        tracked.first_unavailable -= delta
        if tracked.stage1_at is not None:
            tracked.stage1_at -= delta
        if tracked.stage2_at is not None:
            tracked.stage2_at -= delta
