"""Setup, unload and service registration."""
from __future__ import annotations

from custom_components.entity_watchguard.const import (
    DOMAIN,
    SERVICE_CLEAR_NOTIFICATIONS,
    SERVICE_RECOVER_NOW,
)


async def test_setup_registers_services_and_entities(hass, setup_watchguard):
    entry, coordinator = await setup_watchguard()

    assert hass.services.has_service(DOMAIN, SERVICE_RECOVER_NOW)
    assert hass.services.has_service(DOMAIN, SERVICE_CLEAR_NOTIFICATIONS)
    assert coordinator.monitored_domains == ["light", "switch"]
    assert hass.states.get("binary_sensor.entity_watchguard_problem") is not None


async def test_unload_cleans_up(hass, setup_watchguard):
    entry, _ = await setup_watchguard()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert DOMAIN not in hass.data
    assert not hass.services.has_service(DOMAIN, SERVICE_RECOVER_NOW)


async def test_options_update_reloads_entry(hass, setup_watchguard):
    entry, _ = await setup_watchguard()

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "monitored_domains": ["light"]}
    )
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.monitored_domains == ["light"]
