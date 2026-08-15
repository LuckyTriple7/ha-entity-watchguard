"""Exclusion resolution (labels, entities, devices, areas, patterns)."""
from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.entity_watchguard.const import (
    CONF_EXCLUDE_AREAS,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_LABELS,
    CONF_EXCLUDE_PATTERNS,
)
from custom_components.entity_watchguard.filters import build_exclusion, compile_patterns


def _options(**overrides) -> dict:
    return {
        CONF_EXCLUDE_LABELS: [],
        CONF_EXCLUDE_ENTITIES: [],
        CONF_EXCLUDE_DEVICES: [],
        CONF_EXCLUDE_AREAS: [],
        CONF_EXCLUDE_PATTERNS: [],
        **overrides,
    }


def _register(hass, unique_id: str, *, device_id: str | None = None, area_id: str | None = None):
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get_or_create(
        "light", "demo", unique_id, suggested_object_id=unique_id
    )
    if device_id or area_id:
        entry = ent_reg.async_update_entity(entry.entity_id, device_id=device_id, area_id=area_id)
    return entry


async def test_entity_label_excluded(hass):
    entry = _register(hass, "kitchen")
    er.async_get(hass).async_update_entity(entry.entity_id, labels={"offline"})

    exclusion = build_exclusion(hass, _options(exclude_labels=["offline"]))
    assert exclusion.excludes(entry.entity_id)


async def test_explicit_entity_excluded(hass):
    exclusion = build_exclusion(hass, _options(exclude_entities=["light.kitchen"]))
    assert exclusion.excludes("light.kitchen")
    assert not exclusion.excludes("light.hallway")


async def test_pattern_excluded_even_without_registry_entry(hass):
    # Template/YAML entities never reach the entity registry — patterns are the
    # only exemption that still covers them.
    exclusion = build_exclusion(hass, _options(exclude_patterns=[r".*_internet_access$"]))
    assert exclusion.excludes("switch.fritzbox_internet_access")
    assert not exclusion.excludes("switch.fritzbox_wifi")


async def test_device_label_excludes_its_entities(hass):
    config_entry = MockConfigEntry(domain="demo")
    config_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={("demo", "dev1")}
    )
    dr.async_get(hass).async_update_device(device.id, labels={"temp_offline"})
    entry = _register(hass, "kitchen", device_id=device.id)

    exclusion = build_exclusion(hass, _options(exclude_labels=["temp_offline"]))
    assert exclusion.excludes(entry.entity_id)


async def test_excluded_device_id(hass):
    config_entry = MockConfigEntry(domain="demo")
    config_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={("demo", "dev1")}
    )
    entry = _register(hass, "kitchen", device_id=device.id)

    exclusion = build_exclusion(hass, _options(exclude_devices=[device.id]))
    assert exclusion.excludes(entry.entity_id)


async def test_area_inherited_from_device(hass):
    config_entry = MockConfigEntry(domain="demo")
    config_entry.add_to_hass(hass)
    area = ar.async_get(hass).async_create("Holiday home")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={("demo", "dev1")}
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    entry = _register(hass, "kitchen", device_id=device.id)

    exclusion = build_exclusion(hass, _options(exclude_areas=[area.id]))
    assert exclusion.excludes(entry.entity_id)


async def test_area_label_excludes_entities_in_area(hass):
    area = ar.async_get(hass).async_create("Holiday home")
    ar.async_get(hass).async_update(area.id, labels={"offline"})
    entry = _register(hass, "kitchen", area_id=area.id)

    exclusion = build_exclusion(hass, _options(exclude_labels=["offline"]))
    assert exclusion.excludes(entry.entity_id)


async def test_invalid_pattern_is_ignored(hass):
    exclusion = build_exclusion(hass, _options(exclude_patterns=["[unclosed", r"^light\."]))
    assert exclusion.excludes("light.kitchen")
    assert not exclusion.excludes("switch.kitchen")


def test_compile_patterns_drops_invalid():
    assert len(compile_patterns(("[unclosed", "valid"))) == 1
