"""Scanning, recovery and notification logic for Entity Watchguard."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import label_registry as lr
from homeassistant.loader import Integration, async_get_integrations
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHECK_INTERVAL,
    CONF_GRACE_PERIOD,
    CONF_MAX_RECOVERY_ATTEMPTS,
    CONF_MAX_RELOADS_PER_CYCLE,
    CONF_MONITORED_DOMAINS,
    CONF_NOTIFY_DELAY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICE,
    CONF_RELOAD_COOLDOWN,
    CONF_REPAIRS_ENABLED,
    CONF_RETRY_INTERVAL,
    CONF_STAGE1_DELAY,
    CONF_STAGE1_ENABLED,
    CONF_STAGE2_DELAY,
    CONF_STAGE2_ENABLED,
    CONF_STAGE2_MIN_AFFECTED,
    CONF_STARTUP_DELAY,
    DOMAIN,
    NOTIFICATION_ID_PREFIX,
    effective_options,
)
from .filters import Exclusion, build_exclusion

_LOGGER = logging.getLogger(__name__)


def _outcome(entity_id: str, tracked: "Tracked", now: datetime) -> str:
    """How long an entity was gone, and whether we did anything about it."""
    minutes = (now - tracked.first_unavailable).total_seconds() / 60
    if not tracked.attempts:
        return f"{entity_id} (after {minutes:.1f} min)"
    stages = []
    if tracked.stage1_at is not None:
        stages.append("stage 1")
    if tracked.stage2_at is not None:
        stages.append("stage 2")
    return f"{entity_id} (after {minutes:.1f} min, {tracked.attempts} attempt(s): {', '.join(stages)})"


@dataclass(slots=True)
class Tracked:
    """One entity's current unavailability episode.

    Dropped as soon as the entity is available again, so every timer restarts
    from scratch on the next outage.
    """

    first_unavailable: datetime
    name: str
    stage1_at: datetime | None = None
    stage2_at: datetime | None = None
    attempts: int = 0
    # Stage 2 rounds so far; once it hits max_recovery_attempts we stop trying
    # (given_up) instead of reloading someone's integration forever.
    stage2_rounds: int = 0
    given_up: bool = False


@dataclass(slots=True)
class Outage:
    """What gets reported for one domain (notification / repair / push)."""

    entity_ids: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    given_up: int = 0


def _since(tracked: Tracked, use_de: bool) -> str:
    stamp = dt_util.as_local(tracked.first_unavailable).strftime("%d.%m.%Y %H:%M")
    return f"{'seit' if use_de else 'since'} {stamp}"


def _given_up_mark(use_de: bool) -> str:
    return " [aufgegeben]" if use_de else " [gave up]"


def _entity_line(entity_id: str, tracked: Tracked, use_de: bool) -> str:
    mark = _given_up_mark(use_de) if tracked.given_up else ""
    return f"• {tracked.name} ({entity_id}) – {_since(tracked, use_de)}{mark}"


def _device_line(
    device_name: str | None, members: list[tuple[str, "Tracked"]], use_de: bool
) -> str:
    _, first = members[0]
    mark = _given_up_mark(use_de) if all(tracked.given_up for _, tracked in members) else ""
    name = device_name or ("Unbekanntes Gerät" if use_de else "Unknown device")
    label = "Entities" if use_de else "entities"
    listed = ", ".join(entity_id for entity_id, _ in members[:5])
    if len(members) > 5:
        listed += ", …"
    return f"• {name}: {len(members)} {label} ({listed}) – {_since(first, use_de)}{mark}"


@dataclass(slots=True)
class DomainReport:
    """Per-domain result handed to the entities."""

    entity_ids: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    given_up: list[str] = field(default_factory=list)
    # Per-entity rows for the dashboard card; the lists above stay for
    # templates and automations that already use them.
    details: list[dict] = field(default_factory=list)
    since: datetime | None = None
    attempts: int = 0

    @property
    def count(self) -> int:
        return len(self.entity_ids)


class WatchguardCoordinator(DataUpdateCoordinator[dict]):
    """Polls hass.states for unavailable entities and tries to bring them back."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.options = effective_options(entry)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=self.options[CONF_CHECK_INTERVAL]),
        )
        self.entry = entry
        self.last_recovery: datetime | None = None
        self._tracked: dict[str, Tracked] = {}
        self._reloaded_at: dict[str, datetime] = {}
        self._notifications: dict[str, str] = {}
        self._issues: set[str] = set()
        self._pushed: set[str] = set()
        # Set by the Check now button; consumed by the next _build_data().
        self._skip_grace_once = False
        # platform -> iot_class from its manifest (None = could not resolve)
        self._iot_classes: dict[str, str | None] = {}
        # None until HA has finished starting; see async_setup_activation().
        self._active_at: datetime | None = None
        # Resolving labels/devices/areas walks the whole entity registry, which
        # only changes when the user edits something — so cache it and let the
        # registry events invalidate it. See async_setup_registry_listeners().
        self._exclusion: Exclusion | None = None

    # --- lifecycle ------------------------------------------------------
    @property
    def monitored_domains(self) -> list[str]:
        return list(self.options[CONF_MONITORED_DOMAINS])

    @property
    def tracked(self) -> dict[str, Tracked]:
        """Current unavailability episodes, keyed by entity_id."""
        return self._tracked

    @property
    def warming_up(self) -> bool:
        """True while the post-restart grace period is still running.

        Entities trickle in for minutes after a restart, so reporting (and
        recovering) anything during that window would be pure noise.
        """
        return self._active_at is None or dt_util.utcnow() < self._active_at

    def async_setup_activation(self) -> None:
        """Arm the startup grace period once HA is fully started."""

        def _started(_hass: HomeAssistant) -> None:
            delay = timedelta(seconds=self.options[CONF_STARTUP_DELAY])
            self._active_at = dt_util.utcnow() + delay
            _LOGGER.debug("Watchguard arms at %s", self._active_at)

        self.entry.async_on_unload(async_at_started(self.hass, _started))

    def async_setup_registry_listeners(self) -> None:
        """Drop the cached exclusion set whenever a registry changes."""

        @callback
        def _invalidate(_event: Event) -> None:
            self._exclusion = None

        for event_type in (
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            dr.EVENT_DEVICE_REGISTRY_UPDATED,
            ar.EVENT_AREA_REGISTRY_UPDATED,
            lr.EVENT_LABEL_REGISTRY_UPDATED,
        ):
            self.entry.async_on_unload(self.hass.bus.async_listen(event_type, _invalidate))

    async def async_check_now(self) -> None:
        """Scan right now and report what it finds.

        Both grace periods are skipped for this one run: the startup one, and
        the per-entity one — otherwise the button would find the entities but
        still report zero for another `grace_period` seconds, which reads like
        a broken integration.
        """
        if self.warming_up:
            _LOGGER.info("Manual check requested — ending the startup grace period early")
            self._active_at = dt_util.utcnow()
        else:
            _LOGGER.debug("Manual check requested")
        self._skip_grace_once = True
        await self.async_refresh()

    async def async_shutdown(self) -> None:
        self.async_clear_notifications()
        await super().async_shutdown()

    # --- main loop ------------------------------------------------------
    async def _async_update_data(self) -> dict:
        now = dt_util.utcnow()
        if self.warming_up:
            # Keep _tracked empty so timers start from the moment we go live,
            # not from whenever the entity first showed up as unavailable.
            self._tracked.clear()
            return {"warming_up": True, "domains": {}, "total": 0, "last_recovery": None}

        self._async_scan(now)
        await self._async_recover(now)
        await self._async_report(now)
        return self._build_data(now)

    def _async_scan(self, now: datetime) -> None:
        if self._exclusion is None:
            self._exclusion = build_exclusion(self.hass, self.options)
        exclusion = self._exclusion
        seen: set[str] = set()
        appeared: list[str] = []

        for state in self.hass.states.async_all(self.monitored_domains):
            if state.state != STATE_UNAVAILABLE or exclusion.excludes(state.entity_id):
                continue
            seen.add(state.entity_id)
            if (tracked := self._tracked.get(state.entity_id)) is None:
                self._tracked[state.entity_id] = Tracked(first_unavailable=now, name=state.name)
                appeared.append(state.entity_id)
            else:
                tracked.name = state.name

        # Recovered, removed, or newly excluded — either way, stop tracking.
        gone: list[str] = []
        for entity_id in set(self._tracked) - seen:
            tracked = self._tracked.pop(entity_id)
            gone.append(_outcome(entity_id, tracked, now))

        # One line per cycle instead of one per entity: an integration going
        # down takes all of its entities with it.
        if appeared:
            _LOGGER.info("Now unavailable (%d): %s", len(appeared), ", ".join(sorted(appeared)))
        if gone:
            _LOGGER.info("Available again (%d): %s", len(gone), ", ".join(sorted(gone)))

    def _build_data(self, now: datetime) -> dict:
        if self._skip_grace_once:
            self._skip_grace_once = False
            grace = timedelta(0)
        else:
            grace = timedelta(seconds=self.options[CONF_GRACE_PERIOD])
        domains: dict[str, DomainReport] = {domain: DomainReport() for domain in self.monitored_domains}

        for entity_id, tracked in sorted(self._tracked.items()):
            if now - tracked.first_unavailable < grace:
                continue
            report = domains.setdefault(entity_id.split(".")[0], DomainReport())
            report.entity_ids.append(entity_id)
            report.names.append(tracked.name)
            report.attempts += tracked.attempts
            if tracked.given_up:
                report.given_up.append(entity_id)
            report.details.append(
                {
                    "entity_id": entity_id,
                    "name": tracked.name,
                    "since": dt_util.as_local(tracked.first_unavailable).isoformat(),
                    "attempts": tracked.attempts,
                    "given_up": tracked.given_up,
                }
            )
            if report.since is None or tracked.first_unavailable < report.since:
                report.since = tracked.first_unavailable

        return {
            "warming_up": False,
            "domains": domains,
            "total": sum(report.count for report in domains.values()),
            "last_recovery": self.last_recovery,
        }

    # --- recovery -------------------------------------------------------
    async def _async_recover(self, now: datetime) -> None:
        if self.options[CONF_STAGE1_ENABLED]:
            delay = timedelta(seconds=self.options[CONF_STAGE1_DELAY])
            due = [
                entity_id
                for entity_id, tracked in self._tracked.items()
                if not tracked.given_up
                and tracked.stage1_at is None
                and now - tracked.first_unavailable >= delay
            ]
            if due:
                pollable, push = await self._async_split_by_iot_class(due)
                if push:
                    # update_entity is a no-op for push integrations (MQTT, ZHA,
                    # ESPHome …) — skip straight to stage 2 rather than burning
                    # an "attempt" on a call that cannot do anything.
                    _LOGGER.debug("Stage 1 skipped for push entities: %s", sorted(push))
                    for entity_id in push:
                        if (tracked := self._tracked.get(entity_id)) is not None:
                            tracked.stage1_at = now
                if pollable:
                    await self.async_stage1(pollable, now)

        if self.options[CONF_STAGE2_ENABLED]:
            delay = timedelta(seconds=self.options[CONF_STAGE2_DELAY])
            retry = timedelta(seconds=self.options[CONF_RETRY_INTERVAL])
            due = [
                entity_id
                for entity_id, tracked in self._tracked.items()
                if not tracked.given_up
                and now - tracked.first_unavailable >= delay
                and (
                    tracked.stage2_at is None
                    # A device that is simply switched off never comes back from
                    # a single reload — retry, but on a slow interval.
                    or (retry and now - tracked.stage2_at >= retry)
                )
            ]
            if due:
                await self.async_stage2(due, now)

    async def _async_split_by_iot_class(
        self, entity_ids: list[str]
    ) -> tuple[list[str], list[str]]:
        """Split into (pollable, push) using each integration's iot_class.

        Anything we can't resolve counts as pollable — stage 1 is cheap, and a
        wrong guess in that direction only costs one service call.
        """
        ent_reg = er.async_get(self.hass)
        by_platform: dict[str, list[str]] = {}
        unknown: list[str] = []
        for entity_id in entity_ids:
            registry_entry = ent_reg.async_get(entity_id)
            if registry_entry is None:
                unknown.append(entity_id)
            else:
                by_platform.setdefault(registry_entry.platform, []).append(entity_id)

        missing = [platform for platform in by_platform if platform not in self._iot_classes]
        if missing:
            integrations = await async_get_integrations(self.hass, missing)
            for platform, result in integrations.items():
                self._iot_classes[platform] = (
                    result.iot_class if isinstance(result, Integration) else None
                )

        pollable, push = list(unknown), []
        for platform, members in by_platform.items():
            if (self._iot_classes.get(platform) or "").endswith("_push"):
                push += members
            else:
                pollable += members
        return pollable, push

    async def async_stage1(self, entity_ids: list[str], now: datetime | None = None) -> None:
        """Stage 1: ask HA to poll the entities again."""
        now = now or dt_util.utcnow()
        _LOGGER.info(
            "Stage 1 (update_entity) for %d entities: %s",
            len(entity_ids),
            ", ".join(sorted(entity_ids)),
        )
        for entity_id in entity_ids:
            if (tracked := self._tracked.get(entity_id)) is not None:
                tracked.stage1_at = now
                tracked.attempts += 1
        self.last_recovery = now
        # Not blocking: a slow integration must not stall the scan cycle.
        await self.hass.services.async_call(
            "homeassistant", "update_entity", {"entity_id": entity_ids}, blocking=False
        )

    async def async_stage2(self, entity_ids: list[str], now: datetime | None = None) -> None:
        """Stage 2: reload the config entry each entity belongs to."""
        now = now or dt_util.utcnow()
        ent_reg = er.async_get(self.hass)
        cooldown = timedelta(seconds=self.options[CONF_RELOAD_COOLDOWN])
        targets: dict[str, list[str]] = {}

        for entity_id in entity_ids:
            tracked = self._tracked.get(entity_id)
            registry_entry = ent_reg.async_get(entity_id)
            config_entry_id = registry_entry.config_entry_id if registry_entry else None
            # Nothing reloadable (YAML entity), or it's one of ours — mark done
            # so we don't re-evaluate it every cycle.
            if config_entry_id is None or config_entry_id == self.entry.entry_id:
                if tracked is not None:
                    tracked.stage2_at = now
                continue
            targets.setdefault(config_entry_id, []).append(entity_id)

        reloads = 0
        for config_entry_id, affected in targets.items():
            if reloads >= self.options[CONF_MAX_RELOADS_PER_CYCLE]:
                break  # the rest stay due and get picked up next cycle

            last = self._reloaded_at.get(config_entry_id)
            if last is not None and now - last < cooldown:
                continue  # still cooling down; retry after it expires

            target = self.hass.config_entries.async_get_entry(config_entry_id)
            if target is None or target.state is not ConfigEntryState.LOADED:
                _LOGGER.debug(
                    "Stage 2: skipping %s — config entry gone or not loaded", affected
                )
                for entity_id in affected:
                    if (tracked := self._tracked.get(entity_id)) is not None:
                        tracked.stage2_at = now
                continue

            if not self._async_entry_is_broken_enough(ent_reg, config_entry_id, target):
                # Hub-style entries (MQTT, ZHA, Z-Wave) own hundreds of
                # entities. Reloading the whole broker over one dead sensor
                # takes every other entity down with it and doesn't fix a
                # device that is simply offline. Not given_up: if the rest of
                # the hub dies later, the next retry round reloads after all.
                for entity_id in affected:
                    if (tracked := self._tracked.get(entity_id)) is not None:
                        tracked.stage2_at = now
                continue

            _LOGGER.info(
                "Stage 2: stage 1 did not bring back %s — reloading config entry %s (%s)",
                affected,
                target.title,
                target.domain,
            )
            self._reloaded_at[config_entry_id] = now
            self.last_recovery = now
            reloads += 1
            for entity_id in affected:
                if (tracked := self._tracked.get(entity_id)) is not None:
                    tracked.stage2_at = now
                    tracked.attempts += 1
                    tracked.stage2_rounds += 1
                    self._async_check_give_up(entity_id, tracked)
            self.entry.async_create_background_task(
                self.hass,
                self._async_reload(config_entry_id, target.title),
                f"{DOMAIN}_reload_{config_entry_id}",
            )

    def _async_entry_is_broken_enough(
        self, ent_reg: er.EntityRegistry, config_entry_id: str, target: ConfigEntry
    ) -> bool:
        """Is a large enough share of this config entry's entities down?

        A reload fixes an integration that lost its connection, not a single
        device that is switched off — and for hub-style entries the two look
        identical from the outside except for this ratio.
        """
        threshold = self.options[CONF_STAGE2_MIN_AFFECTED]
        if not threshold:
            return True

        owned = [
            registry_entry.entity_id
            for registry_entry in er.async_entries_for_config_entry(ent_reg, config_entry_id)
            if not registry_entry.disabled_by
        ]
        if not owned:
            return True

        down = sum(1 for entity_id in owned if entity_id in self._tracked)
        ratio = down * 100 / len(owned)
        if ratio >= threshold:
            return True

        _LOGGER.info(
            "Stage 2: not reloading %s (%s) — only %d of %d entities affected (%.0f%% < %d%%)",
            target.title,
            target.domain,
            down,
            len(owned),
            ratio,
            threshold,
        )
        return False

    def _async_check_give_up(self, entity_id: str, tracked: Tracked) -> None:
        """Stop trying after the configured number of stage 2 rounds."""
        limit = self.options[CONF_MAX_RECOVERY_ATTEMPTS]
        if not limit or tracked.stage2_rounds < limit:
            return
        tracked.given_up = True
        _LOGGER.warning(
            "Giving up on %s after %d recovery attempt(s) — it stays reported until it returns",
            entity_id,
            tracked.stage2_rounds,
        )

    async def _async_reload(self, config_entry_id: str, title: str) -> None:
        """Reload wrapper — a failing reload must surface as our error, not as
        a bare "Task exception was never retrieved" from the event loop."""
        try:
            await self.hass.config_entries.async_reload(config_entry_id)
        except Exception:  # noqa: BLE001 - background task, log everything
            _LOGGER.exception("Stage 2: reloading config entry %s failed", title)
        else:
            _LOGGER.debug("Stage 2: reload of config entry %s finished", title)

    async def async_recover_now(
        self,
        *,
        domain: str | None = None,
        entity_ids: list[str] | None = None,
        escalate: bool = False,
    ) -> None:
        """Service entry point — run recovery immediately, ignoring the delays."""
        now = dt_util.utcnow()
        selected = [
            entity_id
            for entity_id in self._tracked
            if (entity_ids is None or entity_id in entity_ids)
            and (domain is None or entity_id.startswith(f"{domain}."))
        ]
        if not selected:
            _LOGGER.debug("recover_now: nothing unavailable matches the request")
            return

        await self.async_stage1(selected, now)
        if escalate:
            await self.async_stage2(selected, now)
        await self.async_request_refresh()

    # --- reporting: notifications, repairs, push -------------------------
    async def _async_report(self, now: datetime) -> None:
        outages = self._async_outages(now)
        self._async_update_notifications(outages)
        self._async_update_repairs(outages)
        await self._async_push(outages)

    def _async_outages(self, now: datetime) -> dict[str, Outage]:
        """Entities past the notify delay, grouped per domain and per device."""
        delay = timedelta(seconds=self.options[CONF_NOTIFY_DELAY])
        use_de = self.hass.config.language[:2].lower() == "de"
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)

        # domain -> device key ("" = no device) -> entries
        grouped: dict[str, dict[str, list[tuple[str, Tracked]]]] = {}
        for entity_id, tracked in sorted(self._tracked.items()):
            if now - tracked.first_unavailable < delay:
                continue
            registry_entry = ent_reg.async_get(entity_id)
            device_id = registry_entry.device_id if registry_entry else None
            grouped.setdefault(entity_id.split(".")[0], {}).setdefault(
                device_id or "", []
            ).append((entity_id, tracked))

        outages: dict[str, Outage] = {}
        for domain, by_device in grouped.items():
            outage = Outage()
            for device_id, members in by_device.items():
                outage.entity_ids += [entity_id for entity_id, _ in members]
                outage.given_up += sum(1 for _, tracked in members if tracked.given_up)
                device = dev_reg.async_get(device_id) if device_id else None
                # One line per device beats twelve lines for one dead Shelly.
                if device is not None and len(members) > 1:
                    outage.lines.append(
                        _device_line(device.name_by_user or device.name, members, use_de)
                    )
                else:
                    outage.lines += [
                        _entity_line(entity_id, tracked, use_de) for entity_id, tracked in members
                    ]
            outages[domain] = outage
        return outages

    def _async_update_notifications(self, outages: dict[str, Outage]) -> None:
        if not self.options[CONF_NOTIFY_ENABLED]:
            self._async_clear_notifications()
            return

        use_de = self.hass.config.language[:2].lower() == "de"
        for domain, outage in outages.items():
            notification_id = f"{NOTIFICATION_ID_PREFIX}{domain}"
            title = f"Entity Watchguard – {domain} ({len(outage.entity_ids)})"
            intro = (
                f"Nicht verfügbare Entities in `{domain}`:"
                if use_de
                else f"Unavailable entities in `{domain}`:"
            )
            message = intro + "\n" + "\n".join(outage.lines)
            # Re-create only on change: same notification_id replaces in place,
            # but a needless rewrite marks the notification unread again.
            if self._notifications.get(notification_id) == message:
                continue
            persistent_notification.async_create(self.hass, message, title, notification_id)
            self._notifications[notification_id] = message

        for notification_id in list(self._notifications):
            if notification_id.removeprefix(NOTIFICATION_ID_PREFIX) not in outages:
                persistent_notification.async_dismiss(self.hass, notification_id)
                del self._notifications[notification_id]

    def _async_update_repairs(self, outages: dict[str, Outage]) -> None:
        """Mirror the outages into the Repairs dashboard (optional).

        Not fixable from the UI — there is no button we could offer that the
        Recover now button doesn't already do — but it can be ignored per
        domain, which persistent notifications can't.
        """
        if not self.options[CONF_REPAIRS_ENABLED]:
            self._async_clear_repairs()
            return

        for domain, outage in outages.items():
            issue_id = f"unavailable_{domain}"
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="unavailable_entities",
                translation_placeholders={
                    "domain": domain,
                    "count": str(len(outage.entity_ids)),
                    "entities": ", ".join(outage.entity_ids[:20]),
                },
            )
            self._issues.add(issue_id)

        for issue_id in list(self._issues):
            if issue_id.removeprefix("unavailable_") not in outages:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                self._issues.discard(issue_id)

    async def _async_push(self, outages: dict[str, Outage]) -> None:
        """Fire the configured notify service on state changes only."""
        service = (self.options[CONF_NOTIFY_SERVICE] or "").strip()
        if not service:
            self._pushed.clear()
            return

        use_de = self.hass.config.language[:2].lower() == "de"
        for domain, outage in outages.items():
            if domain in self._pushed:
                continue
            self._pushed.add(domain)
            count = len(outage.entity_ids)
            message = (
                f"{count} Entities in {domain} nicht verfügbar:\n" + "\n".join(outage.lines)
                if use_de
                else f"{count} entities in {domain} unavailable:\n" + "\n".join(outage.lines)
            )
            await self._async_call_notify(service, message)

        for domain in list(self._pushed):
            if domain in outages:
                continue
            self._pushed.discard(domain)
            message = (
                f"{domain}: alle Entities wieder verfügbar"
                if use_de
                else f"{domain}: all entities available again"
            )
            await self._async_call_notify(service, message)

    async def _async_call_notify(self, service: str, message: str) -> None:
        domain, _, service_name = service.partition(".")
        if not service_name:
            _LOGGER.warning("Invalid notify service %r — expected e.g. notify.mobile_app_phone", service)
            return
        try:
            await self.hass.services.async_call(
                domain, service_name, {"title": "Entity Watchguard", "message": message}, blocking=False
            )
        except Exception:  # noqa: BLE001 - a broken notifier must not kill the scan
            _LOGGER.exception("Calling %s failed", service)

    def _async_clear_notifications(self) -> None:
        for notification_id in list(self._notifications):
            persistent_notification.async_dismiss(self.hass, notification_id)
        self._notifications.clear()

    def _async_clear_repairs(self) -> None:
        for issue_id in list(self._issues):
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._issues.clear()

    def async_clear_notifications(self) -> None:
        """Service entry point — drops notifications and repair issues alike."""
        self._async_clear_notifications()
        self._async_clear_repairs()
        self._pushed.clear()
