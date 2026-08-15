"""Buttons: run a scan / a recovery attempt without waiting for the interval."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WatchguardCoordinator
from .entity import WatchguardEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WatchguardCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            WatchguardCheckNowButton(coordinator, entry),
            WatchguardRecoverNowButton(coordinator, entry),
        ]
    )


class WatchguardCheckNowButton(WatchguardEntity, ButtonEntity):
    """Scan immediately instead of waiting for the next check interval."""

    _attr_icon = "mdi:magnify-scan"

    def __init__(self, coordinator: WatchguardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_check_now"
        self._attr_name = "Check now"

    async def async_press(self) -> None:
        await self.coordinator.async_check_now()


class WatchguardRecoverNowButton(WatchguardEntity, ButtonEntity):
    """Stage 1 for everything currently unavailable, ignoring the delays."""

    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: WatchguardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_recover_now"
        self._attr_name = "Recover now"

    async def async_press(self) -> None:
        await self.coordinator.async_recover_now()
