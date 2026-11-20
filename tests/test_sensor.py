"""Per-domain count sensors and registry entries surviving a reload."""
from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from custom_components.entity_watchguard.const import (
    CONF_MONITORED_DOMAINS,
    CONF_STARTUP_DELAY,
    DOMAIN,
)

LIGHT_COUNT = "sensor.entity_watchguard_light_unavailable"
SWITCH_COUNT = "sensor.entity_watchguard_switch_unavailable"


async def _enable(hass, entry, *entity_ids: str) -> None:
    """Enable entities the way the UI does, then reload so they get a state."""
    registry = er.async_get(hass)
    for entity_id in entity_ids:
        registry.async_update_entity(entity_id, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_domain_count_sensors_are_disabled_by_default(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    entry, _ = await setup_watchguard()

    registry = er.async_get(hass)
    for entity_id, domain in ((LIGHT_COUNT, "light"), (SWITCH_COUNT, "switch")):
        registry_entry = registry.async_get(entity_id)
        assert registry_entry is not None
        assert registry_entry.unique_id == f"{entry.entry_id}_{domain}_unavailable"
        assert registry_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entity_id) is None


async def test_domain_count_sensor_counts_unavailable_entities(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    hass.states.async_set("light.hall", "unavailable")
    hass.states.async_set("switch.pump", "on")
    entry, _ = await setup_watchguard()
    await _enable(hass, entry, LIGHT_COUNT, SWITCH_COUNT)

    light = hass.states.get(LIGHT_COUNT)
    assert light.state == "2"
    assert light.attributes["unit_of_measurement"] == "entities"
    assert light.attributes["state_class"] == "measurement"
    assert light.attributes["domain"] == "light"
    assert light.attributes["warming_up"] is False
    assert hass.states.get(SWITCH_COUNT).state == "0"

    hass.states.async_set("light.hall", "on")
    # The reload replaced the coordinator, so fetch the current one.
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(LIGHT_COUNT).state == "1"


async def test_domain_count_sensor_reports_zero_while_warming_up(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    entry, _ = await setup_watchguard(**{CONF_STARTUP_DELAY: 300})
    await _enable(hass, entry, LIGHT_COUNT)

    light = hass.states.get(LIGHT_COUNT)
    assert light.state == "0"
    assert light.attributes["warming_up"] is True


async def test_cleanup_keeps_all_own_entities(hass, setup_watchguard, caplog):
    """The stale-entity cleanup must not remove any of our own entities.

    Up to 1.3.0 the unavailable devices sensor was missing from the cleanup
    list, so its registry entry was removed (and restored by Home Assistant)
    on every setup, with a misleading "no longer watched" log line.
    """
    entry, _ = await setup_watchguard()
    await _enable(hass, entry, LIGHT_COUNT)
    caplog.clear()
    caplog.set_level("INFO", logger="custom_components.entity_watchguard")

    registry = er.async_get(hass)
    before = {
        registry_entry.unique_id: registry_entry.id
        for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert f"{entry.entry_id}_unavailable_devices" in before

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    after = {
        registry_entry.unique_id: registry_entry.id
        for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert after == before
    assert "no longer watched" not in caplog.text
    assert registry.async_get(LIGHT_COUNT).disabled_by is None
    assert hass.states.get(LIGHT_COUNT) is not None


async def test_dropped_domain_removes_its_count_sensor(hass, setup_watchguard):
    entry, _ = await setup_watchguard(["light", "switch"])
    registry = er.async_get(hass)
    assert registry.async_get(SWITCH_COUNT) is not None

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_MONITORED_DOMAINS: ["light"]}
    )
    await hass.async_block_till_done()

    assert registry.async_get(SWITCH_COUNT) is None
    assert registry.async_get(LIGHT_COUNT) is not None
