"""Setup, unload and service registration."""
from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from custom_components.entity_watchguard import _async_sync_card_resource

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
        self._items = [dict(item) for item in items]
        self.loaded = loaded
        self.store = store
        self.created = []
        self.updated = []
        self.deleted = []
        self.load_calls = 0

    def async_items(self):
        return [dict(item) for item in self._items]

    async def async_load(self):
        self.loaded = True
        self.load_calls += 1

    async def async_create_item(self, data):
        self.created.append(data)
        self._items.append({"id": f"new{len(self.created)}", "type": data["res_type"], "url": data["url"]})

    async def async_update_item(self, item_id, data):
        self.updated.append((item_id, data))
        for item in self._items:
            if item["id"] == item_id:
                item.update(type=data["res_type"], url=data["url"])

    async def async_delete_item(self, item_id):
        self.deleted.append(item_id)
        self._items = [item for item in self._items if item["id"] != item_id]


class _FakeLovelace:
    def __init__(self, resources):
        self.resources = resources


def _manifest_version():
    import json
    from pathlib import Path

    import custom_components.entity_watchguard as integration

    return json.loads((Path(integration.__file__).parent / "manifest.json").read_text())["version"]


CARD_URL = f"/entity_watchguard_static/entity-watchguard-card.js?v={_manifest_version()}"
OLD_ITEM = {"id": "old", "type": "module", "url": "/entity_watchguard_static/entity-watchguard-card.js?v=0.9.1"}
HACS_ITEM = {"id": "hacs", "type": "module", "url": "/hacsfiles/ha-entity-watchguard-card/entity-watchguard-card.js"}
OTHER_ITEM = {"id": "other", "type": "module", "url": "/local/some-unrelated-card.js"}


async def test_card_resource_is_created(hass):
    resources = _FakeResources([OTHER_ITEM])
    hass.data["lovelace"] = _FakeLovelace(resources)

    await _async_sync_card_resource(hass)

    assert resources.created == [{"res_type": "module", "url": CARD_URL}]
    assert resources.updated == [] and resources.deleted == []


async def test_card_resource_from_an_older_version_is_updated(hass):
    resources = _FakeResources([OLD_ITEM, OTHER_ITEM])
    hass.data["lovelace"] = _FakeLovelace(resources)

    await _async_sync_card_resource(hass)

    assert resources.updated == [("old", {"res_type": "module", "url": CARD_URL})]
    assert resources.created == [] and resources.deleted == []


async def test_current_card_resource_is_left_alone(hass):
    resources = _FakeResources([{"id": "cur", "type": "module", "url": CARD_URL}])
    hass.data["lovelace"] = _FakeLovelace(resources)

    await _async_sync_card_resource(hass)

    assert resources.created == [] and resources.updated == [] and resources.deleted == []


async def test_duplicate_card_resources_are_collapsed(hass):
    duplicate = {**OLD_ITEM, "id": "dup"}
    resources = _FakeResources([OLD_ITEM, duplicate])
    hass.data["lovelace"] = _FakeLovelace(resources)

    await _async_sync_card_resource(hass)

    assert resources.deleted == ["dup"]
    assert [item["url"] for item in resources.async_items()] == [CARD_URL]


async def test_standalone_hacs_card_is_kept_and_reported(hass, caplog):
    resources = _FakeResources([HACS_ITEM])
    hass.data["lovelace"] = _FakeLovelace(resources)

    await _async_sync_card_resource(hass)

    assert resources.deleted == []
    assert "no longer needed" in caplog.text


async def test_card_sync_loads_an_unloaded_store(hass):
    resources = _FakeResources([], loaded=False)
    hass.data["lovelace"] = _FakeLovelace(resources)

    await _async_sync_card_resource(hass)

    assert resources.load_calls == 1
    assert len(resources.created) == 1


async def test_card_sync_writes_nothing_in_yaml_resource_mode(hass, caplog):
    # No store behind the collection — YAML resources can't be managed
    # programmatically, so the user gets the URL to add themselves.
    resources = _FakeResources([], store=None)
    hass.data["lovelace"] = _FakeLovelace(resources)

    await _async_sync_card_resource(hass)

    assert resources.created == []
    assert CARD_URL in caplog.text


async def test_card_sync_without_lovelace(hass):
    hass.data.pop("lovelace", None)

    await _async_sync_card_resource(hass)  # must not raise


async def test_card_sync_reads_a_plain_dict_as_used_before_ha_2025_2(hass):
    resources = _FakeResources([])
    hass.data["lovelace"] = {"resources": resources}

    await _async_sync_card_resource(hass)

    assert len(resources.created) == 1


async def test_removing_the_entry_removes_only_the_card_resource(hass, setup_watchguard):
    entry, _ = await setup_watchguard()
    resources = _FakeResources([OLD_ITEM, HACS_ITEM, OTHER_ITEM])
    hass.data["lovelace"] = _FakeLovelace(resources)

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert resources.deleted == ["old"]
    assert [item["id"] for item in resources.async_items()] == ["hacs", "other"]


async def test_failing_resource_removal_does_not_block_entry_removal(hass, setup_watchguard):
    entry, _ = await setup_watchguard()

    class _Broken(_FakeResources):
        async def async_delete_item(self, item_id):
            raise RuntimeError("store is broken")

    hass.data["lovelace"] = _FakeLovelace(_Broken([OLD_ITEM]))

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.config_entries.async_get_entry(entry.entry_id) is None


async def test_card_setup_is_scheduled_once(hass, setup_watchguard):
    await setup_watchguard()
    assert hass.data[DOMAIN]["card_scheduled"] is True


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
