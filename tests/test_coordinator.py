"""Scan, grace period, recovery escalation and notifications."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.entity_watchguard.const import (
    CONF_GRACE_PERIOD,
    CONF_MAX_RELOADS_PER_CYCLE,
    CONF_NOTIFY_DELAY,
    CONF_NOTIFY_ENABLED,
    CONF_RELOAD_COOLDOWN,
    CONF_STAGE1_DELAY,
    CONF_STAGE1_ENABLED,
    CONF_STAGE2_DELAY,
    CONF_STAGE2_ENABLED,
    CONF_STARTUP_DELAY,
)

from .conftest import backdate


@pytest.fixture
def update_entity_calls(hass):
    return async_mock_service(hass, "homeassistant", "update_entity")


def _register_entity(hass, config_entry, domain: str, object_id: str):
    """Registry entry + state, so stage 2 can map it back to a config entry."""
    entry = er.async_get(hass).async_get_or_create(
        domain, "demo", object_id, config_entry=config_entry, suggested_object_id=object_id
    )
    hass.states.async_set(entry.entity_id, "unavailable")
    return entry.entity_id


async def test_warming_up_reports_nothing(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    _, coordinator = await setup_watchguard(**{CONF_STARTUP_DELAY: 300})

    assert coordinator.warming_up is True
    assert coordinator.data["warming_up"] is True
    assert coordinator.data["total"] == 0
    assert coordinator.tracked == {}


async def test_reports_unavailable_entities_per_domain(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    hass.states.async_set("light.hallway", "on")
    hass.states.async_set("switch.pump", "unavailable")
    hass.states.async_set("sensor.power", "unavailable")  # domain not watched

    _, coordinator = await setup_watchguard()

    assert coordinator.data["total"] == 2
    assert coordinator.data["domains"]["light"].entity_ids == ["light.kitchen"]
    assert coordinator.data["domains"]["switch"].entity_ids == ["switch.pump"]
    assert "sensor" not in coordinator.data["domains"]


async def test_grace_period_delays_reporting(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    _, coordinator = await setup_watchguard(**{CONF_GRACE_PERIOD: 120})

    assert coordinator.data["total"] == 0

    backdate(coordinator, 200)
    await coordinator.async_refresh()

    assert coordinator.data["total"] == 1
    assert coordinator.data["domains"]["light"].since is not None


async def test_timer_resets_when_entity_recovers(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")
    _, coordinator = await setup_watchguard(**{CONF_GRACE_PERIOD: 120})
    backdate(coordinator, 200)

    hass.states.async_set("light.kitchen", "on")
    await coordinator.async_refresh()
    assert coordinator.tracked == {}

    hass.states.async_set("light.kitchen", "unavailable")
    await coordinator.async_refresh()
    assert coordinator.data["total"] == 0  # grace period starts over


async def test_stage1_calls_update_entity_once(hass, setup_watchguard, update_entity_calls):
    hass.states.async_set("light.kitchen", "unavailable")
    _, coordinator = await setup_watchguard(
        **{CONF_STAGE1_ENABLED: True, CONF_STAGE1_DELAY: 300}
    )
    assert not update_entity_calls

    backdate(coordinator, 400)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(update_entity_calls) == 1
    assert update_entity_calls[0].data["entity_id"] == ["light.kitchen"]
    assert coordinator.last_recovery is not None

    # Same outage, so no second attempt.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(update_entity_calls) == 1


async def test_stage2_reloads_owning_config_entry(hass, setup_watchguard, update_entity_calls):
    other = MockConfigEntry(domain="demo")
    other.add_to_hass(hass)
    other.mock_state(hass, ConfigEntryState.LOADED)
    _register_entity(hass, other, "light", "kitchen")

    _, coordinator = await setup_watchguard(
        **{CONF_STAGE2_ENABLED: True, CONF_STAGE2_DELAY: 900}
    )
    backdate(coordinator, 1000)

    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as reload:
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    reload.assert_awaited_once_with(other.entry_id)


async def test_stage2_respects_cooldown_and_cap(hass, setup_watchguard):
    entries = []
    for index in range(3):
        other = MockConfigEntry(domain=f"demo{index}")
        other.add_to_hass(hass)
        other.mock_state(hass, ConfigEntryState.LOADED)
        _register_entity(hass, other, "light", f"lamp{index}")
        entries.append(other)

    _, coordinator = await setup_watchguard(
        **{
            CONF_STAGE2_ENABLED: True,
            CONF_STAGE2_DELAY: 900,
            CONF_MAX_RELOADS_PER_CYCLE: 2,
            CONF_RELOAD_COOLDOWN: 3600,
        }
    )
    backdate(coordinator, 1000)

    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock) as reload:
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert reload.await_count == 2  # capped

        backdate(coordinator, 1000)
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        # The third entry gets its turn; the first two are still cooling down.
        assert reload.await_count == 3


async def test_stage2_skips_own_and_unregistered_entities(hass, setup_watchguard):
    hass.states.async_set("light.yaml_only", "unavailable")
    entry, coordinator = await setup_watchguard(
        **{CONF_STAGE2_ENABLED: True, CONF_STAGE2_DELAY: 900}
    )
    _register_entity(hass, entry, "switch", "watchguard_own")
    await coordinator.async_refresh()
    backdate(coordinator, 1000)

    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock) as reload:
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    reload.assert_not_awaited()
    # Both are marked done so they aren't re-evaluated every cycle.
    assert all(tracked.stage2_at is not None for tracked in coordinator.tracked.values())


async def test_notification_created_and_dismissed(hass, setup_watchguard):
    hass.states.async_set("light.kitchen", "unavailable")

    with patch(
        "custom_components.entity_watchguard.coordinator.persistent_notification"
    ) as notifications:
        _, coordinator = await setup_watchguard(
            **{CONF_NOTIFY_ENABLED: True, CONF_NOTIFY_DELAY: 0}
        )

        assert notifications.async_create.call_count == 1
        assert notifications.async_create.call_args[0][3] == "entity_watchguard_light"
        assert "light.kitchen" in notifications.async_create.call_args[0][1]

        # Unchanged content must not re-create (that marks it unread again).
        await coordinator.async_refresh()
        assert notifications.async_create.call_count == 1

        hass.states.async_set("light.kitchen", "on")
        await coordinator.async_refresh()
        notifications.async_dismiss.assert_called_once_with(hass, "entity_watchguard_light")


async def test_logs_outage_and_recovery(hass, setup_watchguard, update_entity_calls, caplog):
    hass.states.async_set("light.kitchen", "unavailable")
    _, coordinator = await setup_watchguard(
        **{CONF_STAGE1_ENABLED: True, CONF_STAGE1_DELAY: 300}
    )
    assert "Now unavailable (1): light.kitchen" in caplog.text

    backdate(coordinator, 400)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert "Stage 1 (update_entity) for 1 entities: light.kitchen" in caplog.text

    hass.states.async_set("light.kitchen", "on")
    await coordinator.async_refresh()
    assert "Available again (1): light.kitchen" in caplog.text
    assert "1 attempt(s): stage 1" in caplog.text


async def test_failed_reload_is_logged_as_error(hass, setup_watchguard, caplog):
    other = MockConfigEntry(domain="demo")
    other.add_to_hass(hass)
    other.mock_state(hass, ConfigEntryState.LOADED)
    _register_entity(hass, other, "light", "kitchen")

    _, coordinator = await setup_watchguard(
        **{CONF_STAGE2_ENABLED: True, CONF_STAGE2_DELAY: 900}
    )
    backdate(coordinator, 1000)

    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock, side_effect=RuntimeError("boom")
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert "reloading config entry" in caplog.text
    assert "boom" in caplog.text


async def test_recover_now_service(hass, setup_watchguard, update_entity_calls):
    hass.states.async_set("light.kitchen", "unavailable")
    hass.states.async_set("switch.pump", "unavailable")
    _, coordinator = await setup_watchguard()

    await hass.services.async_call(
        "entity_watchguard", "recover_now", {"domain": "light"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(update_entity_calls) == 1
    assert update_entity_calls[0].data["entity_id"] == ["light.kitchen"]
