"""Config and options flow."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.entity_watchguard.const import (
    CONF_EXCLUDE_ENTITY_CATEGORIES,
    CONF_EXCLUDE_PATTERNS,
    CONF_MONITORED_DOMAINS,
    CONF_NOTIFY_DELAY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_GROUPING,
    CONF_SELECT_ALL_DOMAINS,
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


async def test_options_notify_grouping(hass, setup_watchguard):
    entry, _ = await setup_watchguard()
    # Existing installations keep reporting per domain.
    assert CONF_NOTIFY_GROUPING not in entry.options

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "notifications"}
    )
    schema_keys = {str(key): key for key in result["data_schema"].schema}
    assert schema_keys[CONF_NOTIFY_GROUPING].default() == "domain"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NOTIFY_GROUPING: "device"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_NOTIFY_GROUPING] == "device"


async def test_options_exclude_entity_categories(hass, setup_watchguard):
    entry, _ = await setup_watchguard()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exceptions"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_EXCLUDE_ENTITY_CATEGORIES: ["diagnostic"]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXCLUDE_ENTITY_CATEGORIES] == ["diagnostic"]


async def test_user_flow_select_all_domains(hass):
    hass.states.async_set("light.kitchen", "on")
    hass.states.async_set("cover.garage", "closed")
    hass.states.async_set("automation.morning", "on")
    hass.states.async_set("input_boolean.guest", "off")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MONITORED_DOMAINS: ["sensor"], CONF_SELECT_ALL_DOMAINS: True}
    )
    # The form comes back with every existing domain ticked, helpers left out.
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}
    schema_keys = {str(key): key for key in result["data_schema"].schema}
    assert schema_keys[CONF_MONITORED_DOMAINS].default() == ["cover", "light", "sensor"]
    assert schema_keys[CONF_SELECT_ALL_DOMAINS].default() is False

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MONITORED_DOMAINS: ["cover", "light"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_MONITORED_DOMAINS: ["cover", "light"]}


async def test_domain_picker_is_a_checkbox_list(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    schema_keys = {str(key): key for key in result["data_schema"].schema}
    selector = result["data_schema"].schema[schema_keys[CONF_MONITORED_DOMAINS]]
    assert selector.config["mode"] == "list"
    assert selector.config["multiple"] is True


async def test_options_select_all_domains(hass, setup_watchguard):
    entry, _ = await setup_watchguard()
    hass.states.async_set("vacuum.robot", "docked")
    hass.states.async_set("script.bedtime", "off")

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "domains"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MONITORED_DOMAINS: ["light"], CONF_SELECT_ALL_DOMAINS: True}
    )
    assert result["type"] is FlowResultType.FORM
    schema_keys = {str(key): key for key in result["data_schema"].schema}
    ticked = schema_keys[CONF_MONITORED_DOMAINS].default()
    assert {"light", "vacuum"} <= set(ticked)
    assert "script" not in ticked

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MONITORED_DOMAINS: ticked}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_MONITORED_DOMAINS] == ticked
    assert CONF_SELECT_ALL_DOMAINS not in entry.options
