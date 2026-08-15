"""The Entity Watchguard integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_DOMAIN,
    ATTR_ESCALATE,
    DOMAIN,
    SERVICE_CLEAR_NOTIFICATIONS,
    SERVICE_RECOVER_NOW,
)
from .coordinator import WatchguardCoordinator

PLATFORMS = ["binary_sensor", "button", "sensor"]

RECOVER_NOW_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DOMAIN): cv.string,
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Optional(ATTR_ESCALATE, default=False): cv.boolean,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = WatchguardCoordinator(hass, entry)
    coordinator.async_setup_activation()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _async_register_services(hass)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data = hass.data.get(DOMAIN, {})
        if (coordinator := domain_data.pop(entry.entry_id, None)) is not None:
            coordinator.async_clear_notifications()
        if not domain_data:
            hass.data.pop(DOMAIN, None)
            for service in (SERVICE_RECOVER_NOW, SERVICE_CLEAR_NOTIFICATIONS):
                hass.services.async_remove(DOMAIN, service)
    return unload_ok


def _coordinators(hass: HomeAssistant) -> list[WatchguardCoordinator]:
    return list(hass.data.get(DOMAIN, {}).values())


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_RECOVER_NOW):
        return

    async def _recover_now(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass):
            await coordinator.async_recover_now(
                domain=call.data.get(ATTR_DOMAIN),
                entity_ids=call.data.get(ATTR_ENTITY_ID),
                escalate=call.data[ATTR_ESCALATE],
            )

    async def _clear_notifications(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass):
            coordinator.async_clear_notifications()

    hass.services.async_register(DOMAIN, SERVICE_RECOVER_NOW, _recover_now, RECOVER_NOW_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_NOTIFICATIONS, _clear_notifications)
