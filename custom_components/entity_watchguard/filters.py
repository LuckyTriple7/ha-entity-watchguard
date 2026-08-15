"""Resolving which entities are exempt from watching.

Mirrors what the hand-written template sensors did with
`label_entities('offline')` and `rejectattr('entity_id', 'match', ...)`, plus
device- and area-level exemptions.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_EXCLUDE_AREAS,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_EXCLUDE_LABELS,
    CONF_EXCLUDE_PATTERNS,
)

_LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=32)
def compile_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    """Compile (and cache) exclusion patterns, dropping invalid ones.

    The options flow rejects invalid regexes, so a failure here only happens
    for entries written before that validation existed — warn and carry on
    rather than breaking the whole scan.
    """
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as err:
            _LOGGER.warning("Ignoring invalid exclusion pattern %r: %s", pattern, err)
    return tuple(compiled)


@dataclass(slots=True)
class Exclusion:
    """Pre-resolved exclusion rules for one scan cycle."""

    entity_ids: set[str] = field(default_factory=set)
    patterns: tuple[re.Pattern[str], ...] = ()

    def excludes(self, entity_id: str) -> bool:
        if entity_id in self.entity_ids:
            return True
        return any(pattern.search(entity_id) for pattern in self.patterns)


@callback
def build_exclusion(hass: HomeAssistant, options: dict) -> Exclusion:
    """Resolve labels/devices/areas into concrete entity_ids.

    Registry lookups happen once per scan; the regex patterns stay lazy since
    they also have to cover entities that aren't in the entity registry at all
    (YAML template entities, for instance).
    """
    excluded: set[str] = set(options.get(CONF_EXCLUDE_ENTITIES) or [])
    labels: set[str] = set(options.get(CONF_EXCLUDE_LABELS) or [])
    devices: set[str] = set(options.get(CONF_EXCLUDE_DEVICES) or [])
    areas: set[str] = set(options.get(CONF_EXCLUDE_AREAS) or [])
    integrations: set[str] = set(options.get(CONF_EXCLUDE_INTEGRATIONS) or [])

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    if labels:
        # A label on a device or an area exempts everything below it.
        area_reg = ar.async_get(hass)
        areas |= {area.id for area in area_reg.async_list_areas() if labels & set(area.labels)}
        devices |= {device.id for device in dev_reg.devices.values() if labels & set(device.labels)}

    if labels or devices or areas or integrations:
        for entry in ent_reg.entities.values():
            if entry.entity_id in excluded:
                continue
            # entry.platform is the integration that provides the entity
            # ("shelly", "mqtt", "hue"), not the entity domain.
            if entry.platform in integrations:
                excluded.add(entry.entity_id)
                continue
            if labels & set(entry.labels):
                excluded.add(entry.entity_id)
                continue
            if entry.device_id and entry.device_id in devices:
                excluded.add(entry.entity_id)
                continue
            if areas and _effective_area(dev_reg, entry) in areas:
                excluded.add(entry.entity_id)

    return Exclusion(
        entity_ids=excluded,
        patterns=compile_patterns(tuple(options.get(CONF_EXCLUDE_PATTERNS) or [])),
    )


def _effective_area(dev_reg: dr.DeviceRegistry, entry: er.RegistryEntry) -> str | None:
    """The entity's own area, falling back to its device's area."""
    if entry.area_id:
        return entry.area_id
    if entry.device_id and (device := dev_reg.async_get(entry.device_id)):
        return device.area_id
    return None
