"""Repair issues, notify service and device-grouped notification lines."""
from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.entity_watchguard.const import (
    CONF_NOTIFY_DELAY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICE,
    CONF_REPAIRS_ENABLED,
    DOMAIN,
)


def _device_with_entities(hass, *object_ids: str) -> None:
    """A single device owning several light entities, all unavailable."""
    config_entry = MockConfigEntry(domain="demo")
    config_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={("demo", "shelly1")},
        name="Shelly Kitchen",
    )
    registry = er.async_get(hass)
    for object_id in object_ids:
        entry = registry.async_get_or_create(
            "light", "demo", object_id, config_entry=config_entry, device_id=device.id
        )
        hass.states.async_set(entry.entity_id, "unavailable")


async def test_repair_issue_created_and_removed(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    _, coordinator = await setup_watchguard(
        **{CONF_REPAIRS_ENABLED: True, CONF_NOTIFY_DELAY: 0}
    )

    issue = ir.async_get(hass).async_get_issue(DOMAIN, "unavailable_light")
    assert issue is not None
    assert issue.translation_placeholders["count"] == "1"
    assert issue.translation_placeholders["domain"] == "light"

    hass.states.async_set("light.kitchen", "on")
    await coordinator.async_refresh()

    assert ir.async_get(hass).async_get_issue(DOMAIN, "unavailable_light") is None


async def test_repairs_can_be_switched_off(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    await setup_watchguard(**{CONF_REPAIRS_ENABLED: False, CONF_NOTIFY_DELAY: 0})

    assert ir.async_get(hass).async_get_issue(DOMAIN, "unavailable_light") is None


async def test_notify_service_fires_on_transitions_only(hass, setup_watchguard):
    calls = async_mock_service(hass, "notify", "mobile_app_phone")
    hass.states.async_set("light.kitchen", "unavailable")
    _, coordinator = await setup_watchguard(
        **{
            CONF_NOTIFY_DELAY: 0,
            CONF_NOTIFY_SERVICE: "notify.mobile_app_phone",
            CONF_REPAIRS_ENABLED: False,
        }
    )
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert "light" in calls[0].data["message"]

    # Still unavailable — no repeat push.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(calls) == 1

    hass.states.async_set("light.kitchen", "on")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(calls) == 2
    assert "available again" in calls[1].data["message"]


async def test_notification_groups_entities_by_device(hass, setup_watchguard):
    _device_with_entities(hass, "relay1", "relay2", "relay3")

    with patch(
        "custom_components.entity_watchguard.coordinator.persistent_notification"
    ) as notifications:
        await setup_watchguard(
            **{CONF_NOTIFY_ENABLED: True, CONF_NOTIFY_DELAY: 0, CONF_REPAIRS_ENABLED: False}
        )

    message = notifications.async_create.call_args[0][1]
    assert "Shelly Kitchen: 3 entities" in message
    assert message.count("•") == 1  # one line for the device, not three


async def test_clear_notifications_service_also_clears_issues(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    await setup_watchguard(**{CONF_REPAIRS_ENABLED: True, CONF_NOTIFY_DELAY: 0})
    assert ir.async_get(hass).async_get_issue(DOMAIN, "unavailable_light") is not None

    await hass.services.async_call(DOMAIN, "clear_notifications", {}, blocking=True)

    assert ir.async_get(hass).async_get_issue(DOMAIN, "unavailable_light") is None


async def test_missing_notify_service_does_not_break_the_scan(hass, setup_watchguard, caplog):
    # e.g. the mobile app was removed, or the service name has a typo.
    hass.states.async_set("light.kitchen", "unavailable")
    _, coordinator = await setup_watchguard(
        **{CONF_NOTIFY_DELAY: 0, CONF_NOTIFY_SERVICE: "notify.gone"}
    )

    assert coordinator.data["total"] == 1
    assert "Calling notify.gone failed" in caplog.text


async def test_malformed_notify_service_is_rejected(hass, setup_watchguard, caplog):
    hass.states.async_set("light.kitchen", "unavailable")
    await setup_watchguard(**{CONF_NOTIFY_DELAY: 0, CONF_NOTIFY_SERVICE: "mobile_app_phone"})

    assert "Invalid notify service" in caplog.text
