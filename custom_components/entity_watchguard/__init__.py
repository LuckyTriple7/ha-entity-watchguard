"""The Entity Watchguard integration."""
from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

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

# The dashboard card ships in www/ and is served from here. The same path was
# used up to 0.9.1, so a resource left over from back then is simply updated.
STATIC_URL_PATH = "/entity_watchguard_static"
CARD_PATH = f"{STATIC_URL_PATH}/entity-watchguard-card.js"
# The card lived in its own HACS dashboard repository for 1.0.x. If that copy
# is still installed it is HACS's resource, not ours — we only point it out.
STANDALONE_CARD_MARKER = "/ha-entity-watchguard-card/"
# Survives unloading the entry: a static route can't be removed again, and
# registering it twice on a reload would fail.
STATIC_REGISTERED_KEY = f"{DOMAIN}_static_registered"


async def _async_register_static_path(hass: HomeAssistant) -> None:
    # The http component isn't loaded in the unit test harness.
    if getattr(hass, "http", None) is None or hass.data.get(STATIC_REGISTERED_KEY):
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL_PATH, str(Path(__file__).parent / "www"), cache_headers=False)]
    )
    hass.data[STATIC_REGISTERED_KEY] = True


def _resource_collection(hass: HomeAssistant):
    """Return Lovelace's resource collection, or None if it can't be managed.

    Read through hass.data instead of importing from lovelace.const: the
    LOVELACE_DATA key only exists from HA 2025.2 and the attribute holding the
    resource mode was renamed in 2026.2. Neither is needed here — YAML resource
    mode is recognised by the collection having no store behind it.
    """
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return None
    if isinstance(lovelace, dict):  # HA < 2025.2 kept a plain dict here
        resources = lovelace.get("resources")
    else:
        resources = getattr(lovelace, "resources", None)
    if resources is None or getattr(resources, "store", None) is None:
        return None
    return resources


def _is_own_resource(item: dict) -> bool:
    return str(item.get("url", "")).split("?")[0] == CARD_PATH


async def _async_card_url(hass: HomeAssistant) -> str:
    # ?v= follows the manifest version, so browsers fetch the new card after
    # an update instead of serving a cached copy.
    integration = await async_get_integration(hass, DOMAIN)
    return f"{CARD_PATH}?v={integration.version}"


async def _async_sync_card_resource(hass: HomeAssistant) -> None:
    """Make sure exactly one Lovelace resource points at the bundled card.

    Only the entry under this integration's own static path is created,
    updated or removed; the rest of the user's resource store is left alone.
    async_remove_entry deletes it again when the integration is removed.
    """
    card_url = await _async_card_url(hass)
    resources = _resource_collection(hass)
    if resources is None:
        _LOGGER.info(
            "Lovelace resources are managed in YAML; add %s as a module resource "
            "to use the Entity Watchguard card",
            card_url,
        )
        return
    if not resources.loaded:
        await resources.async_load()

    items = list(resources.async_items() or [])
    own = [item for item in items if _is_own_resource(item)]
    if own:
        first, *duplicates = own
        if first.get("url") != card_url or first.get("type") != "module":
            await resources.async_update_item(first["id"], {"res_type": "module", "url": card_url})
        for item in duplicates:
            await resources.async_delete_item(item["id"])
    else:
        await resources.async_create_item({"res_type": "module", "url": card_url})

    for item in items:
        if STANDALONE_CARD_MARKER in str(item.get("url", "")):
            _LOGGER.warning(
                "The Entity Watchguard card ships with the integration again. The standalone "
                "'Entity Watchguard Card' from HACS (%s) is no longer needed — remove it in "
                "HACS so the dashboard doesn't load the card twice",
                item["url"],
            )


async def _async_remove_card_resource(hass: HomeAssistant) -> None:
    resources = _resource_collection(hass)
    if resources is None:
        return
    if not resources.loaded:
        await resources.async_load()
    for item in list(resources.async_items() or []):
        if _is_own_resource(item):
            await resources.async_delete_item(item["id"])


async def _async_setup_card(hass: HomeAssistant) -> None:
    await _async_register_static_path(hass)

    async def _run(_hass: HomeAssistant) -> None:
        try:
            await _async_sync_card_resource(hass)
        except Exception:  # noqa: BLE001 - the card must never break setup
            _LOGGER.warning("Could not register the dashboard card resource", exc_info=True)

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
    if not domain_data.get("card_scheduled"):
        await _async_setup_card(hass)
        domain_data["card_scheduled"] = True

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
        # hass.data[DOMAIN] also holds the card_scheduled flag, so
        # check for remaining coordinators rather than for an empty dict.
        if not _coordinators(hass):
            hass.data.pop(DOMAIN, None)
            for service in (SERVICE_RECOVER_NOW, SERVICE_CLEAR_NOTIFICATIONS):
                hass.services.async_remove(DOMAIN, service)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Take the card's Lovelace resource with the integration when it is removed.

    Otherwise the resource keeps pointing at a path nothing serves any more,
    and Lovelace retries it on every dashboard render.
    """
    try:
        await _async_remove_card_resource(hass)
    except Exception:  # noqa: BLE001 - removal must go through regardless
        _LOGGER.warning("Could not remove the dashboard card resource", exc_info=True)


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
