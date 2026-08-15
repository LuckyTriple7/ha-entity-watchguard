"""Config entry diagnostics."""
from __future__ import annotations

from custom_components.entity_watchguard.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_report_tracked_entities(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    entry, coordinator = await setup_watchguard()

    data = await async_get_config_entry_diagnostics(hass, entry)

    assert data["warming_up"] is False
    assert data["totals"]["light"] == 1
    assert data["tracked"]["light.kitchen"]["attempts"] == 0
    assert data["tracked"]["light.kitchen"]["first_unavailable"] is not None
    assert data["options"]["monitored_domains"] == ["light", "switch"]
