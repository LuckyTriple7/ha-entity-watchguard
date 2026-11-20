"""Sensors: unavailable entities and devices, last recovery attempt."""
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
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MAX_LISTED
from .coordinator import DeviceReport, DomainReport, WatchguardCoordinator
from .entity import WatchguardEntity, pretty_domain


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WatchguardCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            WatchguardTotalSensor(coordinator, entry),
            WatchguardDeviceSensor(coordinator, entry),
            WatchguardLastRecoverySensor(coordinator, entry),
            *(
                WatchguardDomainCountSensor(coordinator, entry, domain)
                for domain in coordinator.monitored_domains
            ),
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


class WatchguardDomainCountSensor(WatchguardEntity, SensorEntity):
    """Number of unavailable entities in one domain.

    The per-domain binary sensor only says OK/Problem; this one shows how many,
    straight in the state, for tiles, history graphs and long-term statistics.
    Disabled by default — with many watched domains it would add a lot of
    entities that most people never look at.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "entities"
    _attr_icon = "mdi:link-variant-off"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: WatchguardCoordinator, entry: ConfigEntry, domain: str
    ) -> None:
        super().__init__(coordinator, entry)
        self._domain = domain
        self._attr_unique_id = f"{entry.entry_id}_{domain}_unavailable"
        self._attr_name = f"{pretty_domain(domain)} unavailable"

    @property
    def native_value(self) -> int:
        report = (self.coordinator.data or {}).get("domains", {}).get(self._domain)
        return report.count if report else 0

    @property
    def extra_state_attributes(self) -> dict:
        return {"domain": self._domain, "warming_up": self._warming_up}


class WatchguardDeviceSensor(WatchguardEntity, SensorEntity):
    """Devices with at least one unavailable entity.

    A dead Shelly takes a dozen entities with it; counting devices tells how
    much hardware is actually affected.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"
    _attr_icon = "mdi:devices"
    _unrecorded_attributes = frozenset({"unavailable_devices", "details"})

    def __init__(self, coordinator: WatchguardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_unavailable_devices"
        self._attr_name = "Unavailable devices"

    @property
    def _devices(self) -> list[DeviceReport]:
        return (self.coordinator.data or {}).get("devices", [])

    @property
    def native_value(self) -> int:
        return len(self._devices)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        devices = self._devices
        return {
            "warming_up": self.coordinator.data["warming_up"],
            "unavailable_devices": [device.name for device in devices[:MAX_LISTED]],
            "fully_unavailable": sum(1 for device in devices if device.fully_unavailable),
            "entities_without_device": self.coordinator.data.get("entities_without_device", 0),
            "details": [
                {
                    "device_id": device.device_id,
                    "name": device.name,
                    "count": len(device.entity_ids),
                    "entity_ids": device.entity_ids[:MAX_LISTED],
                    "since": dt_util.as_local(device.since).isoformat() if device.since else None,
                    "given_up": device.given_up,
                    "fully_unavailable": device.fully_unavailable,
                }
                for device in devices[:MAX_LISTED]
            ],
            "truncated": len(devices) > MAX_LISTED,
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
