"""Check now / Recover now buttons."""
from __future__ import annotations

from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.entity_watchguard.const import (
    CONF_STAGE1_ENABLED,
    CONF_STARTUP_DELAY,
)


async def _press(hass, entity_id: str) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def test_check_now_scans_immediately(hass, setup_watchguard):
    _, coordinator = await setup_watchguard()
    assert coordinator.data["total"] == 0

    hass.states.async_set("light.kitchen", "unavailable")
    await _press(hass, "button.entity_watchguard_check_now")

    assert coordinator.data["total"] == 1
    assert hass.states.get("binary_sensor.entity_watchguard_light").state == "on"


async def test_check_now_ends_startup_grace_period(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    _, coordinator = await setup_watchguard(**{CONF_STARTUP_DELAY: 300})
    assert coordinator.warming_up is True

    await _press(hass, "button.entity_watchguard_check_now")

    assert coordinator.warming_up is False
    assert coordinator.data["total"] == 1


async def test_recover_now_button(hass, setup_watchguard):
    calls = async_mock_service(hass, "homeassistant", "update_entity")
    hass.states.async_set("light.kitchen", "unavailable")
    # Stage 1 disabled: the button must work regardless of the schedule.
    await setup_watchguard(**{CONF_STAGE1_ENABLED: False})

    await _press(hass, "button.entity_watchguard_recover_now")

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["light.kitchen"]
