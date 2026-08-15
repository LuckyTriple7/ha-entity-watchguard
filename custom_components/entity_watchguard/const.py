"""Constants for the Entity Watchguard integration."""
from __future__ import annotations

DOMAIN = "entity_watchguard"

# --- config/option keys -------------------------------------------------
CONF_MONITORED_DOMAINS = "monitored_domains"
CONF_STARTUP_DELAY = "startup_delay"
CONF_CHECK_INTERVAL = "check_interval"
CONF_GRACE_PERIOD = "grace_period"

CONF_STAGE1_ENABLED = "recover_stage1_enabled"
CONF_STAGE1_DELAY = "recover_stage1_delay"
CONF_STAGE2_ENABLED = "recover_stage2_enabled"
CONF_STAGE2_DELAY = "recover_stage2_delay"
CONF_RELOAD_COOLDOWN = "reload_cooldown"
CONF_MAX_RELOADS_PER_CYCLE = "max_reloads_per_cycle"

CONF_NOTIFY_ENABLED = "notify_enabled"
CONF_NOTIFY_DELAY = "notify_delay"

CONF_EXCLUDE_LABELS = "exclude_labels"
CONF_EXCLUDE_ENTITIES = "exclude_entities"
CONF_EXCLUDE_PATTERNS = "exclude_patterns"
CONF_EXCLUDE_DEVICES = "exclude_devices"
CONF_EXCLUDE_AREAS = "exclude_areas"

# --- defaults -----------------------------------------------------------
DEFAULT_MONITORED_DOMAINS = [
    "light",
    "switch",
    "sensor",
    "binary_sensor",
    "climate",
    "lock",
    "camera",
    "alarm_control_panel",
]

# Domains offered in the picker even when no entity of that domain exists yet.
SUGGESTED_DOMAINS = sorted(
    set(DEFAULT_MONITORED_DOMAINS)
    | {
        "button",
        "cover",
        "device_tracker",
        "fan",
        "humidifier",
        "media_player",
        "number",
        "select",
        "siren",
        "text",
        "update",
        "vacuum",
        "valve",
        "water_heater",
    }
)

DEFAULT_STARTUP_DELAY = 300
DEFAULT_CHECK_INTERVAL = 60
DEFAULT_GRACE_PERIOD = 120

DEFAULT_STAGE1_ENABLED = True
DEFAULT_STAGE1_DELAY = 300
DEFAULT_STAGE2_ENABLED = False
DEFAULT_STAGE2_DELAY = 900
DEFAULT_RELOAD_COOLDOWN = 3600
DEFAULT_MAX_RELOADS_PER_CYCLE = 3

DEFAULT_NOTIFY_ENABLED = True
DEFAULT_NOTIFY_DELAY = 900

DEFAULT_EXCLUDE_LABELS = ["offline", "temp_offline"]

# --- service names ------------------------------------------------------
SERVICE_RECOVER_NOW = "recover_now"
SERVICE_CLEAR_NOTIFICATIONS = "clear_notifications"

ATTR_DOMAIN = "domain"
ATTR_ESCALATE = "escalate"

# --- misc ---------------------------------------------------------------
NOTIFICATION_ID_PREFIX = f"{DOMAIN}_"

DEFAULTS: dict[str, object] = {
    CONF_MONITORED_DOMAINS: DEFAULT_MONITORED_DOMAINS,
    CONF_STARTUP_DELAY: DEFAULT_STARTUP_DELAY,
    CONF_CHECK_INTERVAL: DEFAULT_CHECK_INTERVAL,
    CONF_GRACE_PERIOD: DEFAULT_GRACE_PERIOD,
    CONF_STAGE1_ENABLED: DEFAULT_STAGE1_ENABLED,
    CONF_STAGE1_DELAY: DEFAULT_STAGE1_DELAY,
    CONF_STAGE2_ENABLED: DEFAULT_STAGE2_ENABLED,
    CONF_STAGE2_DELAY: DEFAULT_STAGE2_DELAY,
    CONF_RELOAD_COOLDOWN: DEFAULT_RELOAD_COOLDOWN,
    CONF_MAX_RELOADS_PER_CYCLE: DEFAULT_MAX_RELOADS_PER_CYCLE,
    CONF_NOTIFY_ENABLED: DEFAULT_NOTIFY_ENABLED,
    CONF_NOTIFY_DELAY: DEFAULT_NOTIFY_DELAY,
    CONF_EXCLUDE_LABELS: DEFAULT_EXCLUDE_LABELS,
    CONF_EXCLUDE_ENTITIES: [],
    CONF_EXCLUDE_PATTERNS: [],
    CONF_EXCLUDE_DEVICES: [],
    CONF_EXCLUDE_AREAS: [],
}


def effective_options(entry) -> dict:
    """Merged view of defaults, entry.data and entry.options.

    entry.data only holds what the initial config flow asked for (the domain
    selection); everything else lives in entry.options and falls back to
    DEFAULTS.
    """
    merged = dict(DEFAULTS)
    merged.update(entry.data)
    merged.update(entry.options)
    return merged
