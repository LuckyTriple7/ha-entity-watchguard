# Entity Watchguard

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/github/v/release/LuckyTriple7/ha-entity-watchguard)](https://github.com/LuckyTriple7/ha-entity-watchguard/releases)

Home Assistant custom integration that watches your entities for the `unavailable` state, reports them per domain, and tries to bring them back — the UI-configurable replacement for a pile of hand-written `unavailable` template sensors.

## Features

- One `problem` binary sensor per watched domain (`light`, `switch`, `sensor`, `binary_sensor`, …), listing the affected entities in its attributes, plus one overall problem sensor
- Pick the watched domains in the UI — the picker offers every domain that exists in your instance
- Exceptions by **label**, **entity**, **device**, **area** and **regex pattern** on the entity ID
- Escalating recovery: stage 1 re-polls the entity (`homeassistant.update_entity`), stage 2 reloads the config entry the entity belongs to — each stage separately switchable, with its own delay
- Startup grace period: after a Home Assistant restart the integration stays quiet for a configurable time, because entities need a few minutes to come up
- One persistent notification per domain — it updates itself instead of piling up, and is dismissed automatically once the domain is clean again
- Light on CPU: one in-memory scan per interval (default 60 s), no template rendering and no state-change listeners

## Installation via HACS

1. Open HACS → **Integrations** → Menu (⋮) → **Custom repositories**
2. Enter URL: `https://github.com/LuckyTriple7/ha-entity-watchguard`
3. Category: **Integration** → **Add**
4. Search for **Entity Watchguard** → **Download**
5. Restart Home Assistant

## Configuration

**Settings → Devices & Services → Add Integration → Entity Watchguard**, then pick the domains to watch. Everything else uses defaults and can be changed later under **Configure**:

| Step | Setting | Default | Notes |
|---|---|---|---|
| Timings | Startup delay | 300 s | Counted from the moment HA has finished starting |
| Timings | Check interval | 60 s | How often the states are scanned |
| Timings | Grace period | 120 s | An entity must stay unavailable this long before it is reported |
| Recovery | Stage 1 (update entity) | on, after 300 s | `homeassistant.update_entity` — gentle, only helps polling integrations |
| Recovery | Stage 2 (reload config entry) | off, after 900 s | More effective, but all entities of that integration disappear briefly |
| Recovery | Reload cooldown | 3600 s | Minimum distance between two reloads of the same config entry |
| Recovery | Max reloads per check | 3 | Guards against a reload storm |
| Exceptions | Labels | `offline`, `temp_offline` | Set on an entity, device or area |
| Exceptions | Entities / Devices / Areas | – | Explicit pickers |
| Exceptions | Patterns | – | Regex against the entity ID, e.g. `.*_internet_access$` |
| Notifications | Enabled | on | One persistent notification per domain |
| Notifications | Notify after | 900 s | Meant to fire *after* the recovery attempts have failed |

Only one instance is supported — it watches the whole Home Assistant instance.

## Entities

| Entity | Type | Description |
|---|---|---|
| `binary_sensor.entity_watchguard_<domain>` | problem | ON when the domain has unavailable entities. Attributes: `count`, `unavailable_entities`, `unavailable_names`, `unavailable_since`, `recovery_attempts`, `status` |
| `binary_sensor.entity_watchguard_problem` | problem | ON when any watched domain has a problem. Attributes: `affected_domains`, `unavailable_entities` |
| `sensor.entity_watchguard_unavailable_entities` | count | Total across all watched domains, `per_domain` breakdown in the attributes |
| `sensor.entity_watchguard_last_recovery_attempt` | timestamp | Diagnostic |
| `button.entity_watchguard_check_now` | button | Scan immediately instead of waiting for the check interval — also ends the startup grace period early |
| `button.entity_watchguard_recover_now` | button | Run stage 1 for everything currently unavailable, ignoring the delays |

During the startup grace period every sensor stays `off` and reports `status: warming_up`.

## Services

- `entity_watchguard.recover_now` — recover right now, ignoring the configured delays. Optional `domain`, `entity_id`, and `escalate: true` to also run stage 2.
- `entity_watchguard.clear_notifications` — dismiss all notifications created by this integration.

## Logging

Everything is written to the regular Home Assistant log under `custom_components.entity_watchguard`:

| Level | What |
|---|---|
| INFO | Entities going unavailable and coming back (including how long they were gone and which recovery stages ran), stage 1 and stage 2 attempts |
| WARNING | An exclusion pattern that isn't a valid regex (it is skipped) |
| ERROR | A stage 2 config entry reload that failed, with traceback |
| DEBUG | When the startup grace period ends, skipped reloads, reload completions |

```yaml
logger:
  logs:
    custom_components.entity_watchguard: debug
```

## Notes

- Entities that are not in the entity registry (YAML/template entities) can only be exempted via **patterns** or the **entity** picker; label/device/area exemptions need a registry entry.
- Stage 2 never reloads Entity Watchguard's own config entry, skips entries that are not loaded, and honours the cooldown.
- Replacing template sensors: `label_entities('offline')` maps to the label exceptions, `rejectattr('entity_id', 'match', '.*_internet_access$')` maps to the pattern exceptions.
