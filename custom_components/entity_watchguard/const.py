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
CONF_RETRY_INTERVAL = "retry_interval"
CONF_STAGE2_MIN_AFFECTED = "stage2_min_affected"
CONF_MAX_RECOVERY_ATTEMPTS = "max_recovery_attempts"

CONF_NOTIFY_ENABLED = "notify_enabled"
CONF_NOTIFY_DELAY = "notify_delay"
CONF_REPAIRS_ENABLED = "repairs_enabled"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_NOTIFY_GROUPING = "notify_grouping"

CONF_EXCLUDE_LABELS = "exclude_labels"
CONF_EXCLUDE_ENTITIES = "exclude_entities"
CONF_EXCLUDE_PATTERNS = "exclude_patterns"
CONF_EXCLUDE_DEVICES = "exclude_devices"
CONF_EXCLUDE_AREAS = "exclude_areas"
CONF_EXCLUDE_INTEGRATIONS = "exclude_integrations"
CONF_EXCLUDE_ENTITY_CATEGORIES = "exclude_entity_categories"

# Home Assistant's two entity categories (EntityCategory values); primary
# entities have none. Diagnostic ones (signal strength, firmware update, last
# seen) tend to drop out without the device having a problem.
ENTITY_CATEGORIES = ["config", "diagnostic"]

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
DEFAULT_RETRY_INTERVAL = 3600
# Percent of a config entry's entities that must be unavailable before stage 2
# reloads it. Keeps a single dead MQTT sensor from restarting the whole broker;
# 0 disables the check.
DEFAULT_STAGE2_MIN_AFFECTED = 50
# 0 = keep retrying forever
DEFAULT_MAX_RECOVERY_ATTEMPTS = 3

DEFAULT_NOTIFY_ENABLED = True
DEFAULT_NOTIFY_DELAY = 900
DEFAULT_REPAIRS_ENABLED = True
DEFAULT_NOTIFY_SERVICE = ""

# What the persistent notification and the notify service report: per domain
# (every unavailable entity), per device (only devices that are completely
# down, plus entities without a device), or both. Repair issues stay per domain.
NOTIFY_GROUPING_DOMAIN = "domain"
NOTIFY_GROUPING_DEVICE = "device"
NOTIFY_GROUPING_BOTH = "both"
NOTIFY_GROUPINGS = [NOTIFY_GROUPING_DOMAIN, NOTIFY_GROUPING_DEVICE, NOTIFY_GROUPING_BOTH]
DEFAULT_NOTIFY_GROUPING = NOTIFY_GROUPING_DOMAIN

# Deliberately empty: label names are per-instance, so guessing "offline" here
# would silently hide entities in setups that use that label for something else.
DEFAULT_EXCLUDE_LABELS: list[str] = []

# --- service names ------------------------------------------------------
SERVICE_RECOVER_NOW = "recover_now"
SERVICE_CLEAR_NOTIFICATIONS = "clear_notifications"

ATTR_DOMAIN = "domain"
ATTR_ESCALATE = "escalate"

# --- events -------------------------------------------------------------
# Fired on the HA event bus so recovery history can be recorded and charted
# with standard tools, independent of the (short-lived) outage records.
EVENT_RECOVERY_ATTEMPT = f"{DOMAIN}_recovery_attempt"
EVENT_RECOVERY_RESULT = f"{DOMAIN}_recovery_result"
EVENT_ENTITY_RECOVERED = f"{DOMAIN}_entity_recovered"

TRIGGER_AUTOMATIC = "automatic"
TRIGGER_MANUAL = "manual"

RESULT_SUCCESS = "success"
RESULT_FAILED = "failed"

# --- misc ---------------------------------------------------------------
NOTIFICATION_ID_PREFIX = f"{DOMAIN}_"
# The double underscore keeps it apart from the per-domain ids above.
DEVICE_NOTIFICATION_ID = f"{DOMAIN}__devices"

# A single integration going down can take hundreds of entities with it, and
# the full list would otherwise be written to the state machine (and the
# database) on every scan. Cap what's exposed; `count` stays exact.
MAX_LISTED = 50

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
    CONF_RETRY_INTERVAL: DEFAULT_RETRY_INTERVAL,
    CONF_STAGE2_MIN_AFFECTED: DEFAULT_STAGE2_MIN_AFFECTED,
    CONF_MAX_RECOVERY_ATTEMPTS: DEFAULT_MAX_RECOVERY_ATTEMPTS,
    CONF_NOTIFY_ENABLED: DEFAULT_NOTIFY_ENABLED,
    CONF_NOTIFY_DELAY: DEFAULT_NOTIFY_DELAY,
    CONF_REPAIRS_ENABLED: DEFAULT_REPAIRS_ENABLED,
    CONF_NOTIFY_SERVICE: DEFAULT_NOTIFY_SERVICE,
    CONF_NOTIFY_GROUPING: DEFAULT_NOTIFY_GROUPING,
    CONF_EXCLUDE_LABELS: DEFAULT_EXCLUDE_LABELS,
    CONF_EXCLUDE_ENTITIES: [],
    CONF_EXCLUDE_PATTERNS: [],
    CONF_EXCLUDE_DEVICES: [],
    CONF_EXCLUDE_AREAS: [],
    CONF_EXCLUDE_INTEGRATIONS: [],
    CONF_EXCLUDE_ENTITY_CATEGORIES: [],
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
