"""Config and options flow."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.entity_watchguard.const import (
    CONF_EXCLUDE_PATTERNS,
    CONF_MONITORED_DOMAINS,
    CONF_NOTIFY_DELAY,
    CONF_NOTIFY_ENABLED,
    CONF_STAGE1_DELAY,
    CONF_STAGE1_ENABLED,
    CONF_STAGE2_DELAY,
    CONF_STAGE2_ENABLED,
    DOMAIN,
)


async def test_user_flow_creates_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MONITORED_DOMAINS: ["light", "sensor"]}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MONITORED_DOMAINS] == ["light", "sensor"]


async def test_user_flow_requires_a_domain(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MONITORED_DOMAINS: []}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_MONITORED_DOMAINS: "no_domains"}


async def test_only_one_entry_allowed(hass, make_entry):
    make_entry()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_menu_steps(hass, setup_watchguard):
    entry, _ = await setup_watchguard()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.MENU
    assert set(result["menu_options"]) == {
        "domains",
        "timing",
        "recovery",
        "exceptions",
        "notifications",
    }


async def test_options_merge_instead_of_replace(hass, setup_watchguard):
    entry, _ = await setup_watchguard()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "recovery"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_STAGE1_ENABLED: True,
            CONF_STAGE1_DELAY: 60,
            CONF_STAGE2_ENABLED: True,
            CONF_STAGE2_DELAY: 120,
            "reload_cooldown": 600,
            "max_reloads_per_cycle": 2,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_STAGE1_DELAY] == 60
    # Untouched keys from the other steps survive.
    assert entry.options[CONF_NOTIFY_ENABLED] is False


async def test_options_reject_invalid_pattern(hass, setup_watchguard):
    entry, _ = await setup_watchguard()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exceptions"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_EXCLUDE_PATTERNS: ["[unclosed"]}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_EXCLUDE_PATTERNS: "invalid_pattern"}


async def test_options_notifications_step(hass, setup_watchguard):
    entry, _ = await setup_watchguard()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "notifications"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NOTIFY_ENABLED: True, CONF_NOTIFY_DELAY: 30}
    )
    await hass.async_block_till_done()

    assert entry.options[CONF_NOTIFY_ENABLED] is True
    assert entry.options[CONF_NOTIFY_DELAY] == 30
