"""Entity states and attributes."""
from __future__ import annotations

from custom_components.entity_watchguard.const import CONF_STARTUP_DELAY


async def test_domain_and_overall_sensors(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable", {"friendly_name": "Kitchen"})
    hass.states.async_set("switch.pump", "on")
    await setup_watchguard()

    light = hass.states.get("binary_sensor.entity_watchguard_light")
    assert light.state == "on"
    assert light.attributes["count"] == 1
    assert light.attributes["unavailable_entities"] == ["light.kitchen"]
    assert light.attributes["unavailable_names"] == ["Kitchen"]
    assert light.attributes["unavailable_since"] is not None
    assert light.attributes["device_class"] == "problem"
    # Per-entity rows for the dashboard card.
    assert light.attributes["details"] == [
        {
            "entity_id": "light.kitchen",
            "name": "Kitchen",
            "since": light.attributes["details"][0]["since"],
            "attempts": 0,
            "given_up": False,
        }
    ]

    assert hass.states.get("binary_sensor.entity_watchguard_switch").state == "off"

    overall = hass.states.get("binary_sensor.entity_watchguard_problem")
    assert overall.state == "on"
    assert overall.attributes["affected_domains"] == {"light": 1}


async def test_sensors_stay_quiet_while_warming_up(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    await setup_watchguard(**{CONF_STARTUP_DELAY: 300})

    light = hass.states.get("binary_sensor.entity_watchguard_light")
    assert light.state == "off"
    assert light.attributes["status"] == "warming_up"
    assert hass.states.get("binary_sensor.entity_watchguard_problem").state == "off"


async def test_diagnostic_sensors(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    await setup_watchguard()

    total = hass.states.get("sensor.entity_watchguard_unavailable_entities")
    assert total.state == "1"
    assert total.attributes["per_domain"]["light"] == 1
    assert hass.states.get("sensor.entity_watchguard_last_recovery_attempt").state == "unknown"
