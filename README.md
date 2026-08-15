# Entity Watchguard

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/github/v/release/LuckyTriple7/ha-entity-watchguard)](https://github.com/LuckyTriple7/ha-entity-watchguard/releases)

Home Assistant custom integration that watches your entities for the `unavailable` state, reports them per domain, and tries to bring them back — the UI-configurable replacement for a pile of hand-written `unavailable` template sensors.

## Features

- One `problem` binary sensor per watched domain (`light`, `switch`, `sensor`, `binary_sensor`, …), listing the affected entities in its attributes, plus one overall problem sensor
- Pick the watched domains in the UI — the picker offers every domain that exists in your instance
- Exceptions by **label**, **entity**, **device**, **area**, **integration** and **regex pattern** on the entity ID
- Escalating recovery: stage 1 re-polls the entity (`homeassistant.update_entity`), stage 2 reloads the config entry the entity belongs to. Stage 2 repeats on a slow interval and gives up after a configurable number of attempts
- Stage 1 is skipped automatically for push integrations (MQTT, ZHA, ESPHome …), where re-polling cannot achieve anything
- Startup grace period: after a Home Assistant restart the integration stays quiet for a configurable time, because entities need a few minutes to come up
- Three reporting channels, each switchable: **persistent notifications** (one per domain, self-updating, auto-dismissed, entities grouped per device), **repair issues** (ignorable per domain), and an optional **notify service** for mobile push
- **Check now** / **Recover now** buttons for everything you don't want to wait for
- Bundled **dashboard card** with per-domain rows, per-entity outage details, and a one-click "ignore this entity" action
- Light on CPU: one in-memory scan per interval (default 60 s), no template rendering and no state-change listeners. Long entity lists are kept out of the recorder

## How it works

Every check interval the integration walks the states of the watched domains, keeping the ones that are `unavailable` and not excluded. Each such entity gets an "outage" record with the time it started. From there:

```
unavailable detected
   ├─ grace period ......... short flapping is ignored
   ├─ stage 1 .............. homeassistant.update_entity (skipped for push integrations)
   ├─ stage 2 .............. reload the entity's config entry — only if enough
   │                         of that entry is down, repeated on the retry interval
   ├─ notify delay ......... notification / repair issue / notify service
   └─ give up .............. stop trying, keep reporting
```

The record is dropped the moment the entity is available again, so every timer starts fresh on the next outage.

## Dashboard card

A Lovelace card ships with the integration and registers itself — no resource setup needed. Add a card, search for **Entity Watchguard**, or use YAML:

```yaml
type: custom:entity-watchguard-card
title: Entity Watchguard      # optional
show_ok_domains: true         # also list domains with nothing wrong
show_buttons: true            # Check now / Recover now
allow_ignore: true            # per-entity "ignore" action
ignore_label: offline         # label applied by that action
language: auto                # auto | de | en
```

- One row per watched domain with a counter; click to expand the affected entities
- Each entity shows since when it's been gone, how many recovery attempts ran, and whether Watchguard gave up
- Click an entity for its more-info dialog
- The label button applies your ignore label to that entity — it's excluded from the next scan on, provided that label is listed under Configure → Exceptions. The label is created on first use
- German and English; follows the user's Home Assistant language, or set `language: de` / `en` explicitly
- Has a visual editor

> After a HACS update, do a full **restart** (not just a reload) and hard-refresh the browser — the card is served with a version-stamped URL, but the frontend caches aggressively.

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
| Recovery | Stage 1 (update entity) | on, after 300 s | `homeassistant.update_entity` — gentle. Automatically skipped for push integrations (`iot_class: *_push`), where it would be a no-op |
| Recovery | Stage 2 (reload config entry) | off, after 900 s | More effective, but all entities of that integration disappear briefly |
| Recovery | Reload only above | 50 % | Share of the config entry's entities that must be unavailable. Hub integrations (MQTT, ZHA, Z-Wave) have **one** config entry for hundreds of entities — without this, a single dead sensor would restart the whole broker. `0` disables the check |
| Recovery | Reload cooldown | 3600 s | Minimum distance between two reloads of the same config entry |
| Recovery | Max reloads per check | 3 | Guards against a reload storm |
| Recovery | Repeat stage 2 every | 3600 s | `0` = try stage 2 only once per outage |
| Recovery | Give up after | 3 attempts | `0` = never give up. A device that is simply switched off is not worth reloading forever; it stays reported, just without further attempts |
| Exceptions | Labels | – | Set on an entity, device or area; e.g. an `offline` label for devices you knowingly powered down |
| Exceptions | Entities / Devices / Areas | – | Explicit pickers |
| Exceptions | Integrations | – | Everything provided by that integration, e.g. `shelly`, `mqtt`, `hue` — useful for a whole system you knowingly leave offline |
| Exceptions | Patterns | – | Regex against the entity ID, e.g. `.*_internet_access$` |
| Notifications | Persistent notifications | on | One per domain, self-updating, auto-dismissed. Entities of the same device are collapsed into one line |
| Notifications | Repair issues | on | Mirrors the same outages into Settings → Repairs, where they can be ignored per domain |
| Notifications | Notify after | 900 s | Meant to fire *after* the recovery attempts have failed |
| Notifications | Notify service | – | Optional, e.g. `notify.mobile_app_phone`. Called only when a domain starts or stops having a problem, never on every check |

Only one instance is supported — it watches the whole Home Assistant instance.

## Entities

| Entity | Type | Description |
|---|---|---|
| `binary_sensor.entity_watchguard_<domain>` | problem | ON when the domain has unavailable entities. Attributes: `count`, `unavailable_entities`, `unavailable_names`, `unavailable_since`, `recovery_attempts`, `given_up_entities`, `details` (per-entity rows: `entity_id`, `name`, `since`, `attempts`, `given_up`), `status`, `truncated` |
| `binary_sensor.entity_watchguard_problem` | problem | ON when any watched domain has a problem. Attributes: `affected_domains`, `unavailable_entities` |
| `sensor.entity_watchguard_unavailable_entities` | count | Total across all watched domains, `per_domain` breakdown in the attributes |
| `sensor.entity_watchguard_last_recovery_attempt` | timestamp | Diagnostic |
| `button.entity_watchguard_check_now` | button | Scan immediately instead of waiting for the check interval — also ends the startup grace period early |
| `button.entity_watchguard_recover_now` | button | Run stage 1 for everything currently unavailable, ignoring the delays |

During the startup grace period every sensor stays `off` and reports `status: warming_up`.

The entity lists are capped at 50 entries (`truncated: true` tells you there were more; `count` always stays exact) and are excluded from the recorder, so a large outage doesn't write the same long list into the database on every scan.

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

- Entities that are not in the entity registry (YAML/template entities) can only be exempted via **patterns** or the **entity** picker; label/device/area/integration exemptions need a registry entry.
- Stage 2 never reloads Entity Watchguard's own config entry, skips entries that are not loaded, and honours the cooldown.
- Push detection reads `iot_class` from the integration's manifest. Anything that can't be resolved is treated as pollable — one harmless service call is cheaper than a missed recovery.
- **Nothing showing up?** Check the `status` attribute of a domain sensor: `warming_up` means the startup delay is still running (press **Check now** to end it), `ok` with `count: 0` means nothing matched — verify the domain is actually watched and that the entities are `unavailable`, not `unknown`.
- Replacing template sensors: `label_entities('offline')` maps to the label exceptions, `rejectattr('entity_id', 'match', '.*_internet_access$')` maps to the pattern exceptions.
