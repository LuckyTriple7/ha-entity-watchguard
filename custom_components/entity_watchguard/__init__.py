"""The Entity Watchguard integration."""
from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_DOMAIN,
    ATTR_ESCALATE,
    DOMAIN,
    SERVICE_CLEAR_NOTIFICATIONS,
    SERVICE_RECOVER_NOW,
)
from .coordinator import WatchguardCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "button", "sensor"]

# Bump alongside manifest.json's "version" so browsers pick up card changes
# after a HACS update instead of serving a cached copy of the old script.
CARD_VERSION = "0.7.3"
STATIC_URL_PATH = "/entity_watchguard_static"
CARD_URL = f"{STATIC_URL_PATH}/entity-watchguard-card.js?v={CARD_VERSION}"


async def _async_register_frontend(hass: HomeAssistant) -> None:
    # The `http` component isn't loaded in the unit test harness, so hass.http
    # stays None there; skip registration rather than error.
    if getattr(hass, "http", None) is None:
        return
    www_path = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL_PATH, str(www_path), cache_headers=False)]
    )
    add_extra_js_url(hass, CARD_URL)


RECOVER_NOW_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DOMAIN): cv.string,
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Optional(ATTR_ESCALATE, default=False): cv.boolean,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get("frontend_registered"):
        await _async_register_frontend(hass)
        domain_data["frontend_registered"] = True

    coordinator = WatchguardCoordinator(hass, entry)
    coordinator.async_setup_activation()
    coordinator.async_setup_registry_listeners()
    domain_data[entry.entry_id] = coordinator

    _async_remove_stale_entities(hass, entry, coordinator)
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
        # hass.data[DOMAIN] also holds the frontend_registered flag, so check
        # for remaining coordinators rather than for an empty dict.
        if not _coordinators(hass):
            hass.data.pop(DOMAIN, None)
            for service in (SERVICE_RECOVER_NOW, SERVICE_CLEAR_NOTIFICATIONS):
                hass.services.async_remove(DOMAIN, service)
    return unload_ok


def _async_remove_stale_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: WatchguardCoordinator
) -> None:
    """Drop entities for domains that are no longer watched.

    Otherwise dropping e.g. `camera` from the selection leaves
    binary_sensor.entity_watchguard_camera behind as a permanently
    unavailable leftover.
    """
    expected = {
        f"{entry.entry_id}_problem",
        f"{entry.entry_id}_total_unavailable",
        f"{entry.entry_id}_last_recovery",
        f"{entry.entry_id}_check_now",
        f"{entry.entry_id}_recover_now",
        *(f"{entry.entry_id}_{domain}_problem" for domain in coordinator.monitored_domains),
    }
    registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registry_entry.unique_id not in expected:
            _LOGGER.info(
                "Removing %s — its domain is no longer watched", registry_entry.entity_id
            )
            registry.async_remove(registry_entry.entity_id)


def _coordinators(hass: HomeAssistant) -> list[WatchguardCoordinator]:
    return [
        value
        for value in hass.data.get(DOMAIN, {}).values()
        if isinstance(value, WatchguardCoordinator)
    ]


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
