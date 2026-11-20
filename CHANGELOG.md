# Changelog

All notable changes to this project will be documented in this file.

## [1.6.0] - 2026-11-20
### Added
- **Exclude by entity category** (#11): new option *Excluded entity categories* under Configure → Exceptions, with **Configuration** and **Diagnostic**. Excluded entities are never reported and never recovered, like every other exception. Diagnostic entities (signal strength, firmware update, last seen, uptime) often drop out while the device itself works fine
- Excluded entities don't count when deciding whether a device is completely unavailable, so with Diagnostic excluded a dead device whose signal-strength entity still has a value counts as completely down (device sensor, notifications per device)

### Notes
- Some integrations also put a connection status in the Diagnostic category, e.g. ESPHome's *Status* sensor; excluding it hides that entity too
- Entities without an entity registry entry (YAML templates) have no category and are never excluded by it
- Backward compatible: no category is excluded by default

## [1.5.0] - 2026-11-20
### Added
- **Notifications per device** (#9): new option *Report per* under Configure → Notifications, with **Domain** (default, as before), **Device** or **Both**. It applies to the persistent notification and the notify service; repair issues always stay per domain
  - **Device** reports only devices whose watched entities are *all* unavailable, across all domains in one notification (`Entity Watchguard – devices (…)`), one line per device. A dead Shelly with entities in `light`, `switch` and `sensor` is one line instead of three notifications, and a device where only the firmware-update entity hangs is not announced as dead. Partly unavailable devices show up in the domain view, on the sensors and on the card
  - Unavailable entities that belong to no device (templates, helpers, groups) are listed in their own section, so nothing goes unreported
  - The notify service gets one message per check for everything that went down, and one "Available again: …" message for what came back — a power cut that takes out five devices sends one push, not five
  - The notify delay applies per entity: a device is reported once every watched entity of it is past the delay
- **New attribute `fully_unavailable_devices`** on `sensor.entity_watchguard_unavailable_devices` (#5): the names of the devices whose watched entities are all unavailable, sorted, capped at 50 and kept out of the recorder. `fully_unavailable` stays the count

### Changed
- A device line in a notification now shows when the *earliest* of its entities went down, not the first one in alphabetical order

### Notes
- Backward compatible: existing installations keep reporting per domain, and entities and attributes are unchanged apart from the new one

## [1.4.0] - 2026-11-20
### Added
- **Count sensor per watched domain** (#7): `sensor.entity_watchguard_<domain>_unavailable` shows the number of unavailable entities in that domain directly as its state, where the per-domain problem binary sensor only says OK/Problem. Unit `entities`, state class `measurement` for long-term statistics. Attributes: `domain`, `warming_up`. Stays at `0` during the startup grace period
- The count sensors are **disabled by default**, so watching many domains doesn't add a pile of entities nobody looks at. Enable the ones you want under Settings → Devices & services → Entity Watchguard → Entities

### Fixed
- The unavailable devices sensor (new in 1.3.0) was missing from the list of the integration's own entities that the stale-entity cleanup keeps. On every restart and options change its registry entry was removed and immediately re-created, with a misleading "its domain is no longer watched" line in the log. Home Assistant restores the settings of a re-created entity (name, entity ID, area, icon), so nothing visible was lost

### Notes
- Backward compatible: the problem binary sensors, their attributes and the dashboard card are unchanged. The card keeps reading its counts from the binary sensors and ignores the new sensors

## [1.3.0] - 2026-11-19
### Added
- **New sensor `sensor.entity_watchguard_unavailable_devices`** (#5): counts the devices that have at least one unavailable entity past the grace period. A dead Shelly with twelve entities counts once, so the number says how much hardware is actually affected. Unit `devices`, state class `measurement` for long-term statistics. Attributes:
  - `unavailable_devices` — device names, one entry per device, sorted (the user-given name wins). Two devices with the same name appear twice, because they are counted by device, not by name
  - `fully_unavailable` — how many of these devices have *every* watched entity unavailable, not just some. Entities in unwatched domains, excluded entities and disabled entities don't count
  - `entities_without_device` — unavailable entities that belong to no device (templates, helpers, groups). They count as entities but not as devices
  - `details` — one row per device: `device_id`, `name`, `count`, `entity_ids`, `since`, `given_up`, `fully_unavailable`
  - `truncated`, `warming_up`
- Diagnostics list the affected devices

### Notes
- The same grace period and exclusions apply as for the entity count. The lists are capped at 50 entries and kept out of the recorder, like the entity lists
- Backward compatible: existing entities, attributes and options are unchanged

## [1.2.1] - 2026-11-18
### Changed
- Since Home Assistant 2026.11, HACS is built in as the **Marketplace**. The installation instructions now cover both ways (Settings → Marketplace on 2026.11 and newer, HACS on 2026.10 and older), and the log hint about the retired standalone card points to the Marketplace

## [1.2.0] - 2026-11-18
### Added
- **Recovery events on the Home Assistant event bus** (#4), so recovery history can be recorded and charted with standard tools, independent of Watchguard's outage records and across restarts:
  - `entity_watchguard_recovery_attempt` — one per recovery operation that actually ran: a stage 1 `update_entity` call or a stage 2 config entry reload. Carries `operation_id`, `stage`, `trigger` (`automatic`/`manual`), `timestamp`, `entity_ids`, and for stage 2 the reloaded `config_entry_id`, its title and `integration_domain`. Skipped or merely evaluated operations fire nothing
  - `entity_watchguard_recovery_result` — the outcome of a stage 2 reload (`success`/`failed`, with `error`), linked by `operation_id`
  - `entity_watchguard_entity_recovered` — an entity Watchguard ran recovery for is available again, with outage duration, attempts, the stages that actually ran and the `operation_ids` involved
- A stage 2 reload that completes but leaves the config entry not set up (Home Assistant returns `False` instead of raising) is now logged as a warning and reported as `failed`

### Notes
- Backward compatible: recovery behaviour, entities and options are unchanged

## [1.1.1] - 2026-10-22
### Fixed
- The startup grace period was armed from a worker thread instead of the event loop: the callback passed to `async_at_started` was a plain function, which Home Assistant runs in the executor. It could race the first refresh, so right after setup the integration could briefly still count as warming up. It is a `@callback` now and runs in order on the event loop

## [1.1.0] - 2026-10-22
### Changed
- **The dashboard card ships with the integration again.** The standalone HACS dashboard repository *Entity Watchguard Card* is retired: the card only works with this integration, so it belongs in it (HACS review feedback on hacs/default#10453). It is served from `/entity_watchguard_static/entity-watchguard-card.js`, the same path as up to 0.9.1. Card type and options are unchanged

### Added
- The integration keeps exactly one Lovelace resource for its card: created on start when missing, its `?v=` updated after an update, duplicates collapsed. Only entries under its own static path are touched; nothing else in the resource store is changed
- **The resource is removed when the integration is deleted** (`async_remove_entry`), so no dead resource is left behind for Lovelace to retry on every dashboard render
- In YAML resource mode nothing is written; the log names the URL to add manually
- If the retired standalone card is still installed, a warning in the log says to remove it in HACS. Its resource is not touched — it belongs to HACS
- The card defines its custom element only once, so having both copies loaded during the switch is harmless instead of throwing `has already been defined`
- The resource version is read from `manifest.json` at runtime instead of a hand-kept constant; the card smoke test fails if the card's own `CARD_VERSION` drifts from it
- CI now runs the pytest suite and the card smoke test on every push

### Notes
- The declared minimum stays **2024.12.0**. The resource store is reached through `hass.data["lovelace"]`, not `lovelace.const.LOVELACE_DATA` (2025.2) or the `resource_mode` attribute (2026.2); `StaticPathConfig` needs 2024.7

## [1.0.1] - 2026-09-05
### Fixed
- Label-based device exclusions used `device_registry.devices` as a plain dict (`.values()`), which Home Assistant flags as deprecated and will remove in 2027.9.0. Now resolved through `device_registry.async_entries_for_label()`, the supported indexed lookup

## [1.0.0] - 2026-08-29
### Breaking
- **The dashboard card now lives in its own repository, [ha-entity-watchguard-card](https://github.com/LuckyTriple7/ha-entity-watchguard-card), and has to be installed separately** (HACS → Dashboard → *Entity Watchguard Card*). Up to 0.9.1 the card shipped inside this integration, which registered a Lovelace resource for it under `/entity_watchguard_static/`. Writing the user's shared `lovelace_resources` store from a config entry is not an integration's job — HACS does that as the package manager, visibly and with an uninstall path. Install the card first, then update this integration, and your dashboards never go without it. Card configuration is unchanged
- The minimum Home Assistant version is now declared as **2024.12.0**. The previously declared 2024.6.0 was never accurate: `lovelace.const.LOVELACE_DATA` only exists from 2025.2, the `resource_mode` attribute read in 0.9.1 only from 2026.2, `StaticPathConfig` from 2024.7, and the implicit `OptionsFlow.config_entry` from 2024.12. Dropping the card removed the first three constraints, so the real floor is now the options-flow one

### Added
- A one-time cleanup on start removes the Lovelace resource earlier versions registered under `/entity_watchguard_static/`. Without it, updating would leave a resource pointing at a path nothing serves any more, which Lovelace retries on every dashboard render. Nothing else in the resource store is touched, and the integration never writes to it again
- The per-domain problem sensors expose the domain they cover as a `domain` attribute, so the card no longer has to parse it back out of the entity id
- The two buttons and the aggregate problem sensor are named through translations (`check_now`, `recover_now`, `problem`), which also gives them proper German names. Entity ids are unchanged, and the card matches the buttons on their translation key rather than on their id

### Changed
- The download no longer carries the card

## [0.9.1] - 2026-08-18
### Fixed
- Expanding a domain row often needed two or three clicks, and the row's grey hover highlight flickered. The card re-rendered on every `hass` update — which fires on *any* state change in the system, several times a second on a busy install — and each render replaced the card's entire DOM. A click whose `mousedown` target is removed before `mouseup` never becomes a click event, hence the swallowed taps. The card now only rebuilds when something actually on screen changed (relative ages still tick once a minute)

## [0.9.0] - 2026-08-18
### Added
- After a manual **Recover now** (button or `entity_watchguard.recover_now` service), the integration re-scans automatically 10s and 30s later. Recovery only *starts* things — `update_entity` is dispatched without waiting and a config entry reload runs as its own task — so the refresh right after it still saw the old state and the card kept its old counts until someone pressed **Check now**

### Fixed
- Long entity names no longer push out of the card: names, entity ids, the card title and domain names are truncated with an ellipsis and carry the full text as a tooltip
- `since <time>` moved to its own line below the entity id instead of running on after it
- Entity names and ids are now HTML-escaped before being rendered — a name containing `<`, `&` or a quote could break the card's markup
- The "Ignore (label …)" tooltip used a literal `"` inside a `title="…"` attribute, which cut the tooltip off at the label name

## [0.8.0] - 2026-08-18
### Fixed
- **The card showed "Custom element doesn't exist" in Firefox** (and any other browser Home Assistant doesn't classify as "modern"), while working fine in Chrome. The card was published with `frontend.add_extra_js_url()`, which Home Assistant renders into the index page as `<script>if (isModern) { import("<url>"); }</script>` — `isModern` being a user-agent regex plus a feature check. Where that check rejects, the import never runs and the card silently never registers. It is now registered as a normal **Lovelace resource** (Settings → Dashboards → Resources) instead, the same mechanism every HACS-installed card uses, which Lovelace loads regardless of that check. YAML resource mode still falls back to the old behaviour, since resources can't be managed programmatically there

## [0.7.3] - 2026-08-15
### Changed
- The card follows the **user's Home Assistant language** instead of the browser's, and can be pinned with `language: de` / `language: en` (visual editor has a picker; default `auto`)

### Added
- `tests/card/smoke.js` — renders the card against DOM stubs and asserts on the produced HTML, plus a Card workflow that runs it on every push. The two card bugs in 0.7.1/0.7.2 would both have been caught by it

## [0.7.2] - 2026-08-15
### Fixed
- The card's buttons rendered as plain text ("Jetzt prüfen Wiederherstellen") and the per-entity label button escaped the card's bounds: both used frontend-internal elements (`mwc-button`, `ha-icon-button`) that aren't reliably registered for custom cards. They are plain styled `<button>`s now, as are the editor's inputs
- Pressing a button gives feedback: the button shows a busy state and a short confirmation appears in the card. Previously nothing was visible when nothing was wrong, which was indistinguishable from a broken button
- The card finds its buttons even if the entity ids were renamed, and says so on the card when it can't find them at all

## [0.7.1] - 2026-08-15
### Fixed
- Adding the card from the card picker produced `type: custom:entity_watchguard-card` (underscore) and failed with "Custom element doesn't exist". The stub config built the type from the integration domain instead of the element tag — an underscore isn't valid in a custom element name. Existing cards: change the type to `custom:entity-watchguard-card`

## [0.7.0] - 2026-08-15
### Added
- **Dashboard card** (`custom:entity-watchguard-card`), bundled and self-registering — no Lovelace resource setup. One row per domain with a counter, expandable into the affected entities showing outage duration, recovery attempts and whether Watchguard gave up. Entities open their more-info dialog on click, the label button excludes one from further scans (creating the label if needed), and Check now / Recover now sit at the bottom. Comes with a visual editor and German/English labels
- Domain sensors expose a new `details` attribute — per-entity rows (`entity_id`, `name`, `since`, `attempts`, `given_up`) that the card renders. Kept out of the recorder like the other lists

## [0.6.0] - 2026-08-15
### Added
- Stage 2 now only reloads a config entry when a large enough share of **its** entities is unavailable (new option, default 50 %, `0` disables the check). Hub integrations have a single config entry for hundreds of entities, so one dead MQTT sensor would otherwise restart the whole broker — taking every other MQTT entity down with it, without fixing a device that is simply offline. If the rest of the hub dies later, the next retry round reloads after all

## [0.5.0] - 2026-08-15
### Added
- Exceptions **per integration** — exclude everything provided by e.g. `shelly`, `mqtt` or `hue` in one go, instead of picking devices one by one
- Stage 1 is skipped automatically for push integrations (MQTT, ZHA, ESPHome …). `homeassistant.update_entity` can't do anything for them, so recovery goes straight to stage 2 instead of burning an attempt. Detected via the integration's `iot_class`; anything unresolvable is still treated as pollable

### Changed
- README rewritten for the current feature set, including a flow diagram of an outage and a short troubleshooting section

## [0.4.1] - 2026-08-15
### Fixed
- **Check now** reported nothing even when entities were unavailable: it ended the startup grace period, but the freshly tracked entities then still had to sit out the per-entity grace period (default 120 s), so the sensors stayed at 0. The button now skips both grace periods for that one run — the next scan goes back to the configured grace period

## [0.4.0] - 2026-08-15
### Added
- Stage 2 can now repeat (default: every 60 min) instead of running once per outage, and gives up after a configurable number of attempts (default 3, `0` = never). Given-up entities stay reported and appear in the new `given_up_entities` attribute — they just stop triggering reloads
- **Repair issues** as an optional second output (on by default, switchable under Configure → Notifications). They show up under Settings → Repairs and can be ignored per domain, which persistent notifications can't
- Optional **notify service** (e.g. `notify.mobile_app_phone`), called only when a domain starts or stops having a problem — not on every check
- Notification lines group entities by device: one dead Shelly is one line, not twelve

### Changed
- `entity_watchguard.clear_notifications` now clears repair issues too

## [0.3.0] - 2026-08-15
### Changed
- **Breaking-ish:** the labels `offline` and `temp_offline` are no longer pre-filled as default exceptions. Label names are per-instance — guessing them silently hid entities in setups that use those labels for something else. If you relied on them, set them once under Configure → Exceptions
- Entity lists in the attributes are capped at 50 entries (`truncated: true` marks the cut, `count` stays exact) and are excluded from the recorder — a large outage no longer writes the same long list into the database on every scan
- Label/device/area exceptions are resolved once and cached, invalidated by entity/device/area/label registry events, instead of walking the whole entity registry on every scan

### Fixed
- Removing a domain from the watched list now deletes its binary sensor instead of leaving it behind as a permanently unavailable leftover

## [0.2.0] - 2026-08-15
### Added
- **Check now** button — scans immediately instead of waiting for the check interval. Pressing it also ends the startup grace period early, so a manual check right after a restart actually returns something
- **Recover now** button — runs stage 1 for everything currently unavailable, ignoring the configured delays (same as the `recover_now` service without arguments)

## [0.1.1] - 2026-08-15
### Added
- Log line (INFO) whenever entities go unavailable or come back — the recovery line includes how long the entity was gone and which stages ran, so the HA log shows what happened without turning on debug
- Stage 1 now logs at INFO (was DEBUG) with the entities it re-polls; stage 2 states explicitly that stage 1 did not bring them back
- A failing stage 2 reload is logged as an ERROR with a traceback instead of surfacing as a bare "Task exception was never retrieved"
- README section on enabling debug logging

## [0.1.0] - 2026-08-15
### Added
- Initial release — replaces the hand-written `unavailable` template sensors with a UI-configured integration
- One `problem` binary sensor per watched domain (affected entities in the attributes) plus an overall problem sensor
- Diagnostic sensors: total unavailable entities and last recovery attempt
- Domain selection in the UI; the picker lists every domain present in the instance
- Exceptions by label, entity, device, area and regex pattern on the entity ID
- Escalating recovery: stage 1 `homeassistant.update_entity`, stage 2 config entry reload — each switchable, with delays, reload cooldown and a per-cycle reload cap
- Startup grace period after a Home Assistant restart, so entities that are still coming up aren't reported
- One self-updating, auto-dismissing persistent notification per domain
- Services `recover_now` and `clear_notifications`
- German and English translations
