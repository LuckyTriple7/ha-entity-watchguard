"""The Entity Watchguard integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.start import async_at_started
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

# Up to 0.9.1 the Lovelace card shipped inside this integration, served from
# this static path and registered as a Lovelace resource by the integration.
# The card is its own HACS dashboard repository now
# (https://github.com/LuckyTriple7/ha-entity-watchguard-card), so the path is
# gone and any leftover resource pointing at it has to go with it.
LEGACY_STATIC_URL_PATH = "/entity_watchguard_static/"


async def _async_remove_legacy_card_resource(hass: HomeAssistant) -> None:
    """Delete the Lovelace resource earlier versions of this integration wrote.

    Without this, updating leaves a resource pointing at a path nothing serves
    any more, which Lovelace then retries on every dashboard render, forever.
    Only entries under the old static path are touched — the rest of the
    user's resource store is left alone, and once this has run the integration
    never writes to it again.
    """
    # Read through hass.data instead of importing from lovelace.const: the
    # LOVELACE_DATA key only exists from HA 2025.2, and the attribute holding
    # the resource mode was renamed in 2026.2. Neither is worth raising the
    # minimum HA version for a one-time cleanup.
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return
    if isinstance(lovelace, dict):  # HA < 2025.2 kept a plain dict here
        resources = lovelace.get("resources")
    else:
        resources = getattr(lovelace, "resources", None)
    # YAML resource mode has no store behind it and can't be managed
    # programmatically — those users never got a resource written either.
    if resources is None or getattr(resources, "store", None) is None:
        return

    if not resources.loaded:
        await resources.async_load()
    for item in list(resources.async_items() or []):
        if not str(item.get("url", "")).startswith(LEGACY_STATIC_URL_PATH):
            continue
        _LOGGER.info(
            "Removing the Lovelace resource this integration registered before the card "
            "moved to its own repository: %s. Install 'Entity Watchguard Card' from HACS "
            "to keep using it",
            item["url"],
        )
        await resources.async_delete_item(item["id"])


async def _async_schedule_legacy_cleanup(hass: HomeAssistant) -> None:
    async def _run(_hass: HomeAssistant) -> None:
        try:
            await _async_remove_legacy_card_resource(hass)
        except Exception:  # noqa: BLE001 - cleanup must never break setup
            _LOGGER.warning("Could not clean up the legacy card resource", exc_info=True)

    # Lovelace may not be set up yet when this entry is added; running at
    # start covers both a cold boot and an entry added while HA is running.
    async_at_started(hass, _run)


RECOVER_NOW_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DOMAIN): cv.string,
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Optional(ATTR_ESCALATE, default=False): cv.boolean,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get("legacy_cleanup_scheduled"):
        await _async_schedule_legacy_cleanup(hass)
        domain_data["legacy_cleanup_scheduled"] = True

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
        # hass.data[DOMAIN] also holds the legacy_cleanup_scheduled flag, so
        # check for remaining coordinators rather than for an empty dict.
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
