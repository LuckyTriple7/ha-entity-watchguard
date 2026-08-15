"""Config and options flow for Entity Watchguard."""
from __future__ import annotations

import re

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    AreaSelector,
    AreaSelectorConfig,
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    LabelSelector,
    LabelSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_CHECK_INTERVAL,
    CONF_EXCLUDE_AREAS,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_LABELS,
    CONF_EXCLUDE_PATTERNS,
    CONF_GRACE_PERIOD,
    CONF_MAX_RELOADS_PER_CYCLE,
    CONF_MONITORED_DOMAINS,
    CONF_NOTIFY_DELAY,
    CONF_NOTIFY_ENABLED,
    CONF_RELOAD_COOLDOWN,
    CONF_STAGE1_DELAY,
    CONF_STAGE1_ENABLED,
    CONF_STAGE2_DELAY,
    CONF_STAGE2_ENABLED,
    CONF_STARTUP_DELAY,
    DEFAULT_MONITORED_DOMAINS,
    DOMAIN,
    SUGGESTED_DOMAINS,
    effective_options,
)


def _seconds(min_: int, max_: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=min_, max=max_, step=10, mode=NumberSelectorMode.BOX, unit_of_measurement="s"
        )
    )


@callback
def _domain_selector(hass: HomeAssistant, selected: list[str]) -> SelectSelector:
    """Domains that actually exist in this instance, plus the usual suspects."""
    available = {state.entity_id.split(".")[0] for state in hass.states.async_all()}
    options = sorted(available | set(SUGGESTED_DOMAINS) | set(selected))
    return SelectSelector(
        SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.DROPDOWN)
    )


def _validate_patterns(user_input: dict, errors: dict[str, str]) -> None:
    for pattern in user_input.get(CONF_EXCLUDE_PATTERNS) or []:
        try:
            re.compile(pattern)
        except re.error:
            errors[CONF_EXCLUDE_PATTERNS] = "invalid_pattern"
            return


class EntityWatchguardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input[CONF_MONITORED_DOMAINS]:
                errors[CONF_MONITORED_DOMAINS] = "no_domains"
            else:
                return self.async_create_entry(title="Entity Watchguard", data=user_input)

        selected = (user_input or {}).get(CONF_MONITORED_DOMAINS, DEFAULT_MONITORED_DOMAINS)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MONITORED_DOMAINS, default=selected
                ): _domain_selector(self.hass, selected)
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return EntityWatchguardOptionsFlow()


class EntityWatchguardOptionsFlow(config_entries.OptionsFlow):
    """Everything past the domain selection lives here; defaults cover the rest."""

    async def async_step_init(self, user_input=None) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["domains", "timing", "recovery", "exceptions", "notifications"],
        )

    def _save(self, user_input: dict) -> FlowResult:
        # Each step edits a slice of the options; merge instead of replacing.
        return self.async_create_entry(title="", data={**self.config_entry.options, **user_input})

    @property
    def _current(self) -> dict:
        return effective_options(self.config_entry)

    async def async_step_domains(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_MONITORED_DOMAINS]:
                errors[CONF_MONITORED_DOMAINS] = "no_domains"
            else:
                return self._save(user_input)

        selected = list(self._current[CONF_MONITORED_DOMAINS])
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MONITORED_DOMAINS, default=selected
                ): _domain_selector(self.hass, selected)
            }
        )
        return self.async_show_form(step_id="domains", data_schema=schema, errors=errors)

    async def async_step_timing(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self._save(user_input)

        current = self._current
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_STARTUP_DELAY, default=current[CONF_STARTUP_DELAY]
                ): _seconds(0, 3600),
                vol.Required(
                    CONF_CHECK_INTERVAL, default=current[CONF_CHECK_INTERVAL]
                ): _seconds(10, 3600),
                vol.Required(
                    CONF_GRACE_PERIOD, default=current[CONF_GRACE_PERIOD]
                ): _seconds(0, 3600),
            }
        )
        return self.async_show_form(step_id="timing", data_schema=schema)

    async def async_step_recovery(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self._save(user_input)

        current = self._current
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_STAGE1_ENABLED, default=current[CONF_STAGE1_ENABLED]
                ): BooleanSelector(),
                vol.Required(
                    CONF_STAGE1_DELAY, default=current[CONF_STAGE1_DELAY]
                ): _seconds(30, 86400),
                vol.Required(
                    CONF_STAGE2_ENABLED, default=current[CONF_STAGE2_ENABLED]
                ): BooleanSelector(),
                vol.Required(
                    CONF_STAGE2_DELAY, default=current[CONF_STAGE2_DELAY]
                ): _seconds(60, 86400),
                vol.Required(
                    CONF_RELOAD_COOLDOWN, default=current[CONF_RELOAD_COOLDOWN]
                ): _seconds(60, 86400),
                vol.Required(
                    CONF_MAX_RELOADS_PER_CYCLE, default=current[CONF_MAX_RELOADS_PER_CYCLE]
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=20, step=1, mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="recovery", data_schema=schema)

    async def async_step_exceptions(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            _validate_patterns(user_input, errors)
            if not errors:
                return self._save(user_input)

        current = self._current
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_EXCLUDE_LABELS, default=list(current[CONF_EXCLUDE_LABELS])
                ): LabelSelector(LabelSelectorConfig(multiple=True)),
                vol.Optional(
                    CONF_EXCLUDE_ENTITIES, default=list(current[CONF_EXCLUDE_ENTITIES])
                ): EntitySelector(
                    EntitySelectorConfig(
                        multiple=True, domain=list(current[CONF_MONITORED_DOMAINS])
                    )
                ),
                vol.Optional(
                    CONF_EXCLUDE_DEVICES, default=list(current[CONF_EXCLUDE_DEVICES])
                ): DeviceSelector(DeviceSelectorConfig(multiple=True)),
                vol.Optional(
                    CONF_EXCLUDE_AREAS, default=list(current[CONF_EXCLUDE_AREAS])
                ): AreaSelector(AreaSelectorConfig(multiple=True)),
                vol.Optional(
                    CONF_EXCLUDE_PATTERNS, default=list(current[CONF_EXCLUDE_PATTERNS])
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(current[CONF_EXCLUDE_PATTERNS]),
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="exceptions", data_schema=schema, errors=errors)

    async def async_step_notifications(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self._save(user_input)

        current = self._current
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NOTIFY_ENABLED, default=current[CONF_NOTIFY_ENABLED]
                ): BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_DELAY, default=current[CONF_NOTIFY_DELAY]
                ): _seconds(0, 86400),
            }
        )
        return self.async_show_form(step_id="notifications", data_schema=schema)
