# Changelog

All notable changes to this project will be documented in this file.

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
