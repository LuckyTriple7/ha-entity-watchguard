"""Diagnostics support for Entity Watchguard."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import WatchguardCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    coordinator: WatchguardCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "options": coordinator.options,
        "warming_up": coordinator.warming_up,
        "last_recovery": coordinator.last_recovery,
        "tracked": {
            entity_id: {
                "first_unavailable": tracked.first_unavailable,
                "stage1_at": tracked.stage1_at,
                "stage2_at": tracked.stage2_at,
                "attempts": tracked.attempts,
                "stage2_rounds": tracked.stage2_rounds,
                "given_up": tracked.given_up,
            }
            for entity_id, tracked in coordinator.tracked.items()
        },
        "totals": {
            domain: report.count
            for domain, report in (coordinator.data or {}).get("domains", {}).items()
        },
        "devices": {
            report.device_id: {
                "entity_ids": report.entity_ids,
                "given_up": report.given_up,
                "fully_unavailable": report.fully_unavailable,
            }
            for report in (coordinator.data or {}).get("devices", [])
        },
        "entities_without_device": (coordinator.data or {}).get("entities_without_device", 0),
    }
