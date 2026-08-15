"""Diagnostic sensors: total unavailable count and last recovery attempt."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DomainReport, WatchguardCoordinator
from .entity import WatchguardEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WatchguardCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            WatchguardTotalSensor(coordinator, entry),
            WatchguardLastRecoverySensor(coordinator, entry),
        ]
    )


class WatchguardTotalSensor(WatchguardEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "entities"
    _attr_icon = "mdi:link-variant-off"

    def __init__(self, coordinator: WatchguardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_total_unavailable"
        self._attr_name = "Unavailable entities"

    @property
    def native_value(self) -> int:
        return self.coordinator.data["total"] if self.coordinator.data else 0

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        domains: dict[str, DomainReport] = self.coordinator.data["domains"]
        return {
            "warming_up": self.coordinator.data["warming_up"],
            "per_domain": {domain: report.count for domain, report in domains.items()},
        }


class WatchguardLastRecoverySensor(WatchguardEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: WatchguardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_recovery"
        self._attr_name = "Last recovery attempt"

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_recovery
