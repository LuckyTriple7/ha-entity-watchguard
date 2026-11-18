"""Recovery events on the HA event bus (recovery history for automations)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.entity_watchguard.const import (
    CONF_STAGE1_DELAY,
    CONF_STAGE1_ENABLED,
    CONF_STAGE2_DELAY,
    CONF_STAGE2_ENABLED,
    CONF_STAGE2_MIN_AFFECTED,
    EVENT_ENTITY_RECOVERED,
    EVENT_RECOVERY_ATTEMPT,
    EVENT_RECOVERY_RESULT,
)

from .conftest import backdate


@pytest.fixture
def update_entity_calls(hass):
    return async_mock_service(hass, "homeassistant", "update_entity")


@pytest.fixture
def attempts(hass):
    return async_capture_events(hass, EVENT_RECOVERY_ATTEMPT)


@pytest.fixture
def results(hass):
    return async_capture_events(hass, EVENT_RECOVERY_RESULT)


@pytest.fixture
def recovered(hass):
    return async_capture_events(hass, EVENT_ENTITY_RECOVERED)


def _register_entity(hass, config_entry, domain: str, object_id: str) -> str:
    entry = er.async_get(hass).async_get_or_create(
        domain, "demo", object_id, config_entry=config_entry, suggested_object_id=object_id
    )
    hass.states.async_set(entry.entity_id, "unavailable")
    return entry.entity_id


def _loaded_entry(hass, domain: str = "demo", title: str = "Demo") -> MockConfigEntry:
    entry = MockConfigEntry(domain=domain, title=title)
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry


async def test_stage1_fires_one_attempt_event(
    hass, setup_watchguard, update_entity_calls, attempts, recovered
):
    hass.states.async_set("light.kitchen", "unavailable")
    hass.states.async_set("light.hall", "unavailable")
    entry, coordinator = await setup_watchguard(
        **{CONF_STAGE1_ENABLED: True, CONF_STAGE1_DELAY: 300}
    )
    assert not attempts

    backdate(coordinator, 400)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(attempts) == 1
    data = attempts[0].data
    assert data["watchguard_entry_id"] == entry.entry_id
    assert data["stage"] == 1
    assert data["trigger"] == "automatic"
    assert data["entity_ids"] == ["light.hall", "light.kitchen"]
    assert data["config_entry_id"] is None
    assert data["integration_domain"] is None
    assert data["operation_id"]
    assert data["timestamp"]

    # Same outage, no second operation -> no second event.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(attempts) == 1

    # Coming back links to the operation that covered it.
    hass.states.async_set("light.kitchen", "on")
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(recovered) == 1
    back = recovered[0].data
    assert back["entity_id"] == "light.kitchen"
    assert back["attempts"] == 1
    assert back["stages"] == [1]
    assert back["operation_ids"] == [data["operation_id"]]
    assert back["last_operation_id"] == data["operation_id"]
    assert back["duration_seconds"] >= 400


async def test_stage2_fires_attempt_and_success_result(
    hass, setup_watchguard, attempts, results
):
    other = _loaded_entry(hass)
    entity_id = _register_entity(hass, other, "light", "kitchen")
    _, coordinator = await setup_watchguard(
        **{CONF_STAGE2_ENABLED: True, CONF_STAGE2_DELAY: 900}
    )
    backdate(coordinator, 1000)

    with patch.object(
        hass.config_entries, "async_reload", AsyncMock(return_value=True)
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert len(attempts) == 1
    attempt = attempts[0].data
    assert attempt["stage"] == 2
    assert attempt["trigger"] == "automatic"
    assert attempt["entity_ids"] == [entity_id]
    assert attempt["config_entry_id"] == other.entry_id
    assert attempt["config_entry_title"] == "Demo"
    assert attempt["integration_domain"] == "demo"
    assert attempt["integration_domains"] == ["demo"]

    assert len(results) == 1
    result = results[0].data
    assert result["operation_id"] == attempt["operation_id"]
    assert result["result"] == "success"
    assert result["error"] is None
    assert result["config_entry_id"] == other.entry_id


async def test_stage2_failed_reload_fires_failed_result(
    hass, setup_watchguard, results
):
    other = _loaded_entry(hass)
    _register_entity(hass, other, "light", "kitchen")
    _, coordinator = await setup_watchguard(
        **{CONF_STAGE2_ENABLED: True, CONF_STAGE2_DELAY: 900}
    )
    backdate(coordinator, 1000)

    with patch.object(
        hass.config_entries, "async_reload", AsyncMock(side_effect=RuntimeError("boom"))
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert len(results) == 1
    assert results[0].data["result"] == "failed"
    assert results[0].data["error"] == "boom"


async def test_stage2_reload_without_setup_counts_as_failed(
    hass, setup_watchguard, results
):
    other = _loaded_entry(hass)
    _register_entity(hass, other, "light", "kitchen")
    _, coordinator = await setup_watchguard(
        **{CONF_STAGE2_ENABLED: True, CONF_STAGE2_DELAY: 900}
    )
    backdate(coordinator, 1000)

    with patch.object(
        hass.config_entries, "async_reload", AsyncMock(return_value=False)
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert len(results) == 1
    assert results[0].data["result"] == "failed"
    assert results[0].data["error"] == "setup failed"


async def test_manual_recovery_is_marked_manual(
    hass, setup_watchguard, update_entity_calls, attempts
):
    other = _loaded_entry(hass)
    entity_id = _register_entity(hass, other, "light", "kitchen")
    await setup_watchguard()

    with patch.object(
        hass.config_entries, "async_reload", AsyncMock(return_value=True)
    ):
        await hass.services.async_call(
            "entity_watchguard", "recover_now", {"escalate": True}, blocking=True
        )
        await hass.async_block_till_done()

    assert [event.data["stage"] for event in attempts] == [1, 2]
    assert all(event.data["trigger"] == "manual" for event in attempts)
    assert attempts[0].data["entity_ids"] == [entity_id]
    assert attempts[0].data["integration_domains"] == ["demo"]
    assert attempts[0].data["operation_id"] != attempts[1].data["operation_id"]


async def test_skipped_reload_fires_nothing(hass, setup_watchguard, attempts, results):
    """A hub entry below the threshold is evaluated, not reloaded: no event."""
    broker = _loaded_entry(hass, domain="mqtt", title="Broker")
    registry = er.async_get(hass)
    for index in range(10):
        healthy = registry.async_get_or_create(
            "light", "mqtt", f"lamp{index}", config_entry=broker
        )
        hass.states.async_set(healthy.entity_id, "on")
    _register_entity(hass, broker, "light", "dead_sensor")

    _, coordinator = await setup_watchguard(
        **{CONF_STAGE2_ENABLED: True, CONF_STAGE2_DELAY: 900, CONF_STAGE2_MIN_AFFECTED: 50}
    )
    backdate(coordinator, 1000)

    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    reload.assert_not_awaited()
    assert not attempts
    assert not results


async def test_no_recovered_event_without_recovery_or_when_removed(
    hass, setup_watchguard, update_entity_calls, recovered
):
    hass.states.async_set("light.kitchen", "unavailable")
    hass.states.async_set("light.hall", "unavailable")
    _, coordinator = await setup_watchguard(
        **{CONF_STAGE1_ENABLED: True, CONF_STAGE1_DELAY: 300}
    )

    # Back before any recovery ran -> nothing to report.
    hass.states.async_set("light.hall", "on")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert not recovered

    # Recovery ran, but the entity was removed instead of coming back.
    backdate(coordinator, 400)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    hass.states.async_remove("light.kitchen")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert not recovered
