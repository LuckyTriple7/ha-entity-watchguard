"""Setup, unload and service registration."""
from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from custom_components.entity_watchguard import _async_remove_legacy_card_resource

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


class _FakeResources:
    """Stand-in for Lovelace's ResourceStorageCollection."""

    def __init__(self, items, *, loaded=True, store=object()):
        self._items = list(items)
        self.loaded = loaded
        self.store = store
        self.deleted = []
        self.load_calls = 0

    def async_items(self):
        return list(self._items)

    async def async_load(self):
        self.loaded = True
        self.load_calls += 1

    async def async_delete_item(self, item_id):
        self.deleted.append(item_id)
        self._items = [item for item in self._items if item["id"] != item_id]


class _FakeLovelace:
    def __init__(self, resources):
        self.resources = resources


LEGACY_ITEM = {"id": "legacy", "url": "/entity_watchguard_static/entity-watchguard-card.js?v=0.9.1"}
HACS_ITEM = {"id": "hacs", "url": "/hacsfiles/ha-entity-watchguard-card/entity-watchguard-card.js"}
OTHER_ITEM = {"id": "other", "url": "/local/some-unrelated-card.js"}


async def test_legacy_card_resource_is_removed(hass):
    resources = _FakeResources([LEGACY_ITEM, HACS_ITEM, OTHER_ITEM])
    hass.data["lovelace"] = _FakeLovelace(resources)

    await _async_remove_legacy_card_resource(hass)

    assert resources.deleted == ["legacy"]
    assert [item["id"] for item in resources.async_items()] == ["hacs", "other"]


async def test_legacy_cleanup_loads_an_unloaded_store(hass):
    resources = _FakeResources([LEGACY_ITEM], loaded=False)
    hass.data["lovelace"] = _FakeLovelace(resources)

    await _async_remove_legacy_card_resource(hass)

    assert resources.load_calls == 1
    assert resources.deleted == ["legacy"]


async def test_legacy_cleanup_is_a_no_op_in_yaml_resource_mode(hass):
    # No store behind the collection — YAML resources can't be managed
    # programmatically, and those users never had a resource written.
    resources = _FakeResources([LEGACY_ITEM], store=None)
    hass.data["lovelace"] = _FakeLovelace(resources)

    await _async_remove_legacy_card_resource(hass)

    assert resources.deleted == []


async def test_legacy_cleanup_without_lovelace(hass):
    hass.data.pop("lovelace", None)

    await _async_remove_legacy_card_resource(hass)  # must not raise


async def test_legacy_cleanup_reads_a_plain_dict_as_used_before_ha_2025_2(hass):
    resources = _FakeResources([LEGACY_ITEM])
    hass.data["lovelace"] = {"resources": resources}

    await _async_remove_legacy_card_resource(hass)

    assert resources.deleted == ["legacy"]


async def test_legacy_cleanup_is_scheduled_once(hass, setup_watchguard):
    await setup_watchguard()
    assert hass.data[DOMAIN]["legacy_cleanup_scheduled"] is True


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
