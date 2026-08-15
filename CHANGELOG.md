# Changelog

All notable changes to this project will be documented in this file.

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
