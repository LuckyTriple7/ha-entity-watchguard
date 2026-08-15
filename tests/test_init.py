"""Setup, unload and service registration."""
from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from custom_components.entity_watchguard.const import (
    CONF_MONITORED_DOMAINS,
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


async def test_frontend_registration_is_skipped_without_http(hass, setup_watchguard):
    # hass.http is None in the test harness — registration must not raise, and
    # the guard flag still gets set so a reload doesn't retry it.
    await setup_watchguard()
    assert hass.data[DOMAIN]["frontend_registered"] is True


async def test_dropped_domain_entity_is_removed(hass, setup_watchguard):
    entry, _ = await setup_watchguard(["light", "switch"])
    assert hass.states.get("binary_sensor.entity_watchguard_switch") is not None

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_MONITORED_DOMAINS: ["light"]}
    )
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.entity_watchguard_switch") is None
    unique_ids = {
        registry_entry.unique_id
        for registry_entry in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
    }
    assert f"{entry.entry_id}_switch_problem" not in unique_ids
    assert f"{entry.entry_id}_light_problem" in unique_ids
