"""Notifications and pushes per device (notify_grouping)."""
from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.entity_watchguard.const import (
    CONF_NOTIFY_DELAY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_GROUPING,
    CONF_NOTIFY_SERVICE,
    CONF_REPAIRS_ENABLED,
    DEVICE_NOTIFICATION_ID,
    NOTIFY_GROUPING_BOTH,
    NOTIFY_GROUPING_DEVICE,
)

from .conftest import backdate

PATCH_TARGET = "custom_components.entity_watchguard.coordinator.persistent_notification"
BASE = {CONF_NOTIFY_ENABLED: True, CONF_NOTIFY_DELAY: 0, CONF_REPAIRS_ENABLED: False}


def _device(hass, key: str, name: str, entities: dict[str, str]) -> str:
    """Create a device owning `entities` ({"light.x": state, ...}); return its id."""
    config_entry = MockConfigEntry(domain="demo")
    config_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={("demo", key)}, name=name
    )
    registry = er.async_get(hass)
    for entity_id, state in entities.items():
        domain, object_id = entity_id.split(".")
        entry = registry.async_get_or_create(
            domain,
            "demo",
            f"{key}_{object_id}",
            suggested_object_id=object_id,
            config_entry=config_entry,
            device_id=device.id,
        )
        assert entry.entity_id == entity_id
        hass.states.async_set(entity_id, state)
    return device.id


def _setup_states(hass) -> None:
    # Completely down, with entities in two domains.
    _device(
        hass,
        "shelly",
        "Shelly Kitchen",
        {"light.relay1": "unavailable", "light.relay2": "unavailable", "switch.relay3": "unavailable"},
    )
    # Only partly down: the LED still works.
    _device(hass, "plug", "Attic Plug", {"switch.attic": "unavailable", "light.attic_led": "on"})
    # Belongs to no device.
    hass.states.async_set("light.template", "unavailable", {"friendly_name": "Template Light"})


def _created(notifications) -> dict[str, tuple[str, str]]:
    """notification_id -> (title, message) of the last create per id."""
    return {
        call.args[3]: (call.args[2], call.args[1])
        for call in notifications.async_create.call_args_list
    }


async def test_device_mode_reports_completely_unavailable_devices(hass, setup_watchguard):
    _setup_states(hass)
    with patch(PATCH_TARGET) as notifications:
        await setup_watchguard(**BASE, **{CONF_NOTIFY_GROUPING: NOTIFY_GROUPING_DEVICE})

    created = _created(notifications)
    # One notification across all domains, no per-domain ones.
    assert list(created) == [DEVICE_NOTIFICATION_ID]
    title, message = created[DEVICE_NOTIFICATION_ID]
    assert title == "Entity Watchguard – devices (1 device, 1 without device)"
    assert "Unavailable devices:\n• Shelly Kitchen: 3 entities" in message
    assert "Attic Plug" not in message
    assert "Unavailable, without a device:\n• Template Light (light.template)" in message


async def test_device_notification_disappears_when_the_device_is_back(hass, setup_watchguard):
    _device(hass, "shelly", "Shelly Kitchen", {"light.relay1": "unavailable"})
    with patch(PATCH_TARGET) as notifications:
        _, coordinator = await setup_watchguard(
            **BASE, **{CONF_NOTIFY_GROUPING: NOTIFY_GROUPING_DEVICE}
        )
        title, message = _created(notifications)[DEVICE_NOTIFICATION_ID]
        assert title == "Entity Watchguard – devices (1 device)"
        assert "• Shelly Kitchen: 1 entity (light.relay1)" in message

        hass.states.async_set("light.relay1", "on")
        await coordinator.async_refresh()

    notifications.async_dismiss.assert_called_once_with(hass, DEVICE_NOTIFICATION_ID)


async def test_both_reports_domains_and_devices(hass, setup_watchguard):
    _setup_states(hass)
    with patch(PATCH_TARGET) as notifications:
        await setup_watchguard(**BASE, **{CONF_NOTIFY_GROUPING: NOTIFY_GROUPING_BOTH})

    created = _created(notifications)
    assert set(created) == {
        DEVICE_NOTIFICATION_ID,
        "entity_watchguard_light",
        "entity_watchguard_switch",
    }
    # The domain view still shows the partly unavailable plug.
    assert "switch.attic" in created["entity_watchguard_switch"][1]


async def test_domain_mode_is_the_default(hass, setup_watchguard):
    _setup_states(hass)
    with patch(PATCH_TARGET) as notifications:
        await setup_watchguard(**BASE)

    assert set(_created(notifications)) == {"entity_watchguard_light", "entity_watchguard_switch"}


async def test_device_mode_push_is_batched_and_sent_on_changes_only(hass, setup_watchguard):
    calls = async_mock_service(hass, "notify", "mobile_app_phone")
    _setup_states(hass)
    _, coordinator = await setup_watchguard(
        **{
            CONF_NOTIFY_DELAY: 0,
            CONF_REPAIRS_ENABLED: False,
            CONF_NOTIFY_SERVICE: "notify.mobile_app_phone",
            CONF_NOTIFY_GROUPING: NOTIFY_GROUPING_DEVICE,
        }
    )
    await hass.async_block_till_done()

    # One message for everything that went down, not one per domain.
    assert len(calls) == 1
    message = calls[0].data["message"]
    assert "Shelly Kitchen: 3 entities" in message
    assert "Template Light (light.template)" in message
    assert "Attic Plug" not in message

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(calls) == 1

    # A second device going down is announced on its own.
    _device(hass, "hall", "Hall Lamp", {"light.hall": "unavailable"})
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(calls) == 2
    assert "Hall Lamp" in calls[1].data["message"]
    assert "Shelly Kitchen" not in calls[1].data["message"]

    for entity_id in ("light.relay1", "light.relay2", "switch.relay3", "light.template"):
        hass.states.async_set(entity_id, "on")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(calls) == 3
    assert calls[2].data["message"] == "Available again: Shelly Kitchen, Template Light"


async def test_device_mode_sends_no_domain_push(hass, setup_watchguard):
    calls = async_mock_service(hass, "notify", "mobile_app_phone")
    # Partly down only: nothing to report per device.
    _device(hass, "plug", "Attic Plug", {"switch.attic": "unavailable", "light.attic_led": "on"})
    await setup_watchguard(
        **{
            CONF_NOTIFY_DELAY: 0,
            CONF_REPAIRS_ENABLED: False,
            CONF_NOTIFY_SERVICE: "notify.mobile_app_phone",
            CONF_NOTIFY_GROUPING: NOTIFY_GROUPING_DEVICE,
        }
    )
    await hass.async_block_till_done()
    assert calls == []


async def test_device_waits_until_every_entity_is_past_the_notify_delay(hass, setup_watchguard):
    _device(
        hass, "shelly", "Shelly Kitchen", {"light.relay1": "unavailable", "light.relay2": "on"}
    )
    with patch(PATCH_TARGET) as notifications:
        _, coordinator = await setup_watchguard(
            **{**BASE, CONF_NOTIFY_DELAY: 600, CONF_NOTIFY_GROUPING: NOTIFY_GROUPING_DEVICE}
        )
        backdate(coordinator, 900)
        # relay2 only just went down: the device is not completely down yet
        # as far as the notify delay is concerned.
        hass.states.async_set("light.relay2", "unavailable")
        await coordinator.async_refresh()
        assert DEVICE_NOTIFICATION_ID not in _created(notifications)

        backdate(coordinator, 900)
        await coordinator.async_refresh()
        assert DEVICE_NOTIFICATION_ID in _created(notifications)
