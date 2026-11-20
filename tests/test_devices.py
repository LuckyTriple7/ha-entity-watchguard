"""Device-level reporting: the "Unavailable devices" sensor."""
from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import EntityCategory
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.entity_watchguard.const import (
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_ENTITY_CATEGORIES,
    CONF_GRACE_PERIOD,
    CONF_STARTUP_DELAY,
)

from .conftest import backdate

SENSOR = "sensor.entity_watchguard_unavailable_devices"


def _device(hass, key: str, name: str, entities: dict[str, str], **device_kwargs) -> str:
    """Create a device owning `entities` ({"light.x": state, ...}); return its id."""
    config_entry = MockConfigEntry(domain="demo")
    config_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={("demo", key)},
        name=name,
        **device_kwargs,
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


async def test_counts_devices_not_entities(hass, setup_watchguard):
    shelly = _device(
        hass,
        "shelly",
        "Shelly Kitchen",
        {"light.relay1": "unavailable", "light.relay2": "unavailable", "switch.relay3": "unavailable"},
    )
    _device(
        hass,
        "plug",
        "Attic Plug",
        {"switch.attic": "unavailable", "light.attic_led": "on"},
    )
    # A template-style entity without any device.
    hass.states.async_set("light.template", "unavailable")
    await setup_watchguard()

    assert hass.states.get("sensor.entity_watchguard_unavailable_entities").state == "5"

    sensor = hass.states.get(SENSOR)
    assert sensor.state == "2"
    assert sensor.attributes["unit_of_measurement"] == "devices"
    assert sensor.attributes["state_class"] == "measurement"
    # Sorted by name, one entry per device.
    assert sensor.attributes["unavailable_devices"] == ["Attic Plug", "Shelly Kitchen"]
    assert sensor.attributes["entities_without_device"] == 1
    assert sensor.attributes["fully_unavailable"] == 1
    # Only the Shelly is completely down; the plug's LED still works.
    assert sensor.attributes["fully_unavailable_devices"] == ["Shelly Kitchen"]
    assert sensor.attributes["truncated"] is False

    attic, kitchen = sensor.attributes["details"]
    assert kitchen["device_id"] == shelly
    assert kitchen["count"] == 3
    assert kitchen["entity_ids"] == ["light.relay1", "light.relay2", "switch.relay3"]
    assert kitchen["fully_unavailable"] is True
    assert kitchen["given_up"] is False
    assert kitchen["since"] is not None
    # The LED still works, so the plug is only partly down.
    assert attic["count"] == 1
    assert attic["fully_unavailable"] is False


async def test_devices_with_the_same_name_are_counted_separately(hass, setup_watchguard):
    _device(hass, "plug1", "Shelly Plug S", {"switch.plug_one": "unavailable"})
    _device(hass, "plug2", "Shelly Plug S", {"switch.plug_two": "unavailable"})
    await setup_watchguard()

    sensor = hass.states.get(SENSOR)
    assert sensor.state == "2"
    assert sensor.attributes["unavailable_devices"] == ["Shelly Plug S", "Shelly Plug S"]
    assert len({row["device_id"] for row in sensor.attributes["details"]}) == 2


async def test_user_given_device_name_wins(hass, setup_watchguard):
    device_id = _device(hass, "plug", "Shelly Plug S", {"switch.plug": "unavailable"})
    dr.async_get(hass).async_update_device(device_id, name_by_user="Coffee Machine")
    await setup_watchguard()

    assert hass.states.get(SENSOR).attributes["unavailable_devices"] == ["Coffee Machine"]


async def test_unwatched_and_excluded_entities_do_not_block_fully_unavailable(
    hass, setup_watchguard
):
    _device(
        hass,
        "shelly",
        "Shelly Kitchen",
        {
            "light.relay": "unavailable",
            # Not a watched domain: irrelevant for "fully unavailable".
            "sensor.relay_power": "12",
            # Excluded by the user: irrelevant too.
            "switch.relay_child_lock": "off",
        },
    )
    await setup_watchguard(**{CONF_EXCLUDE_ENTITIES: ["switch.relay_child_lock"]})

    sensor = hass.states.get(SENSOR)
    assert sensor.state == "1"
    assert sensor.attributes["fully_unavailable"] == 1
    assert sensor.attributes["details"][0]["fully_unavailable"] is True


async def test_grace_period_applies_to_devices(hass, setup_watchguard):
    _device(hass, "plug", "Attic Plug", {"switch.attic": "unavailable"})
    _, coordinator = await setup_watchguard(**{CONF_GRACE_PERIOD: 120})

    assert hass.states.get(SENSOR).state == "0"

    backdate(coordinator, 200)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(SENSOR).state == "1"


async def test_device_count_drops_when_entities_recover(hass, setup_watchguard):
    _device(hass, "plug", "Attic Plug", {"switch.attic": "unavailable"})
    _, coordinator = await setup_watchguard()
    assert hass.states.get(SENSOR).state == "1"

    hass.states.async_set("switch.attic", "on")
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    sensor = hass.states.get(SENSOR)
    assert sensor.state == "0"
    assert sensor.attributes["unavailable_devices"] == []
    assert sensor.attributes["details"] == []


async def test_device_sensor_while_warming_up(hass, setup_watchguard):
    _device(hass, "plug", "Attic Plug", {"switch.attic": "unavailable"})
    await setup_watchguard(**{CONF_STARTUP_DELAY: 300})

    sensor = hass.states.get(SENSOR)
    assert sensor.state == "0"
    assert sensor.attributes["warming_up"] is True
    assert sensor.attributes["unavailable_devices"] == []


async def test_excluded_diagnostic_entities_are_ignored(hass, setup_watchguard):
    """A dead device whose diagnostic entity still reports counts as fully down."""
    device_id = _device(hass, "plug", "Attic Plug", {"switch.attic": "unavailable"})
    config_entry_id = dr.async_get(hass).async_get(device_id).primary_config_entry
    registry = er.async_get(hass)
    for object_id, state in (("attic_rssi", "-70"), ("attic_last_seen", "unavailable")):
        registry.async_get_or_create(
            "sensor",
            "demo",
            f"plug_{object_id}",
            suggested_object_id=object_id,
            config_entry=hass.config_entries.async_get_entry(config_entry_id),
            device_id=device_id,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        hass.states.async_set(f"sensor.{object_id}", state)

    await setup_watchguard(
        ["switch", "sensor"], **{CONF_EXCLUDE_ENTITY_CATEGORIES: ["diagnostic"]}
    )

    # The unavailable diagnostic entity isn't reported ...
    assert hass.states.get("sensor.entity_watchguard_unavailable_entities").state == "1"
    sensor = hass.states.get(SENSOR)
    # ... and the RSSI entity that still has a value doesn't keep the plug
    # from counting as completely down.
    assert sensor.attributes["fully_unavailable_devices"] == ["Attic Plug"]
