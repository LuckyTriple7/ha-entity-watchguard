# Changelog

All notable changes to this project will be documented in this file.

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
