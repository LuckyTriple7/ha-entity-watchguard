"""Shared base for Entity Watchguard entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WatchguardCoordinator


class WatchguardEntity(CoordinatorEntity[WatchguardCoordinator]):
    """All entities hang off one service device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WatchguardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Entity Watchguard",
            manufacturer="LuckyTriple7",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _warming_up(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.get("warming_up"))
