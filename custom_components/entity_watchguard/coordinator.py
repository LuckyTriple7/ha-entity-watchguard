"""Scanning, recovery and notification logic for Entity Watchguard."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import label_registry as lr
from homeassistant.loader import Integration, async_get_integrations
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from .const import (
    CONF_CHECK_INTERVAL,
    CONF_GRACE_PERIOD,
    CONF_MAX_RECOVERY_ATTEMPTS,
    CONF_MAX_RELOADS_PER_CYCLE,
    CONF_MONITORED_DOMAINS,
    CONF_NOTIFY_DELAY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_GROUPING,
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
    DEVICE_NOTIFICATION_ID,
    DOMAIN,
    EVENT_ENTITY_RECOVERED,
    EVENT_RECOVERY_ATTEMPT,
    EVENT_RECOVERY_RESULT,
    NOTIFICATION_ID_PREFIX,
    NOTIFY_GROUPING_DEVICE,
    NOTIFY_GROUPING_DOMAIN,
    RESULT_FAILED,
    RESULT_SUCCESS,
    TRIGGER_AUTOMATIC,
    TRIGGER_MANUAL,
    effective_options,
)
from .filters import Exclusion, build_exclusion

_LOGGER = logging.getLogger(__name__)

# Stage 1 fires `update_entity` non-blocking and stage 2 reloads config entries
# in the background, so the refresh at the end of a manual recovery still sees
# the pre-recovery state. Re-scan at these offsets (seconds) so a dashboard
# updates on its own instead of needing a manual "Check now" afterwards.
RECOVERY_FOLLOWUP_DELAYS = (10, 30)


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
    # IDs of the recovery operations (stage 1 calls, stage 2 reloads) that
    # covered this entity, so the "recovered" event can point back to them.
    operation_ids: list[str] = field(default_factory=list)
    stages_run: set[int] = field(default_factory=set)


@dataclass(slots=True)
class Outage:
    """What gets reported for one domain (notification / repair / push)."""

    entity_ids: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    given_up: int = 0


@dataclass(slots=True)
class DeviceOutage:
    """What gets reported per device (notification / push).

    Only devices whose watched entities are *all* unavailable count, so a hung
    firmware-update entity doesn't announce a working device as dead. Entities
    without a device can't be grouped and are listed on their own.
    """

    # device id -> (name, line), sorted by name
    devices: dict[str, tuple[str, str]] = field(default_factory=dict)
    # entity id -> (name, line) for entities without a device
    entities: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def names(self) -> dict[str, str]:
        """Every reported key (device id or entity id) -> display name."""
        return {key: name for key, (name, _) in (self.devices | self.entities).items()}

    def only(self, keys: set[str]) -> "DeviceOutage":
        """The part of this outage whose keys are in `keys`."""
        return DeviceOutage(
            devices={key: value for key, value in self.devices.items() if key in keys},
            entities={key: value for key, value in self.entities.items() if key in keys},
        )


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
    first = min((tracked for _, tracked in members), key=lambda item: item.first_unavailable)
    mark = _given_up_mark(use_de) if all(tracked.given_up for _, tracked in members) else ""
    name = device_name or ("Unbekanntes Gerät" if use_de else "Unknown device")
    if len(members) == 1:
        label = "Entity" if use_de else "entity"
    else:
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


@dataclass(slots=True)
class DeviceReport:
    """One device with at least one unavailable entity past the grace period."""

    device_id: str
    name: str
    entity_ids: list[str] = field(default_factory=list)
    since: datetime | None = None
    # Every reported entity of the device has been given up on.
    given_up: bool = False
    # Every watched entity of the device is unavailable, not just some of them.
    fully_unavailable: bool = False


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
        # Devices (and device-less entities) already announced via the notify
        # service in device mode: key -> name, for the "available again" text.
        self._pushed_devices: dict[str, str] = {}
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
        # Pending post-recovery re-scans; see _async_schedule_recovery_followups.
        self._followup_cancels: list[CALLBACK_TYPE] = []

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

        # @callback keeps this on the event loop: a plain function would be
        # handed to the executor and race the first refresh.
        @callback
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
        self._async_cancel_recovery_followups()
        self.async_clear_notifications()
        await super().async_shutdown()

    # --- main loop ------------------------------------------------------
    async def _async_update_data(self) -> dict:
        now = dt_util.utcnow()
        if self.warming_up:
            # Keep _tracked empty so timers start from the moment we go live,
            # not from whenever the entity first showed up as unavailable.
            self._tracked.clear()
            return {
                "warming_up": True,
                "domains": {},
                "total": 0,
                "devices": [],
                "entities_without_device": 0,
                "last_recovery": None,
            }

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
            if tracked.operation_ids and self._is_back(entity_id, exclusion):
                self._async_fire_entity_recovered(entity_id, tracked, now)

        # One line per cycle instead of one per entity: an integration going
        # down takes all of its entities with it.
        if appeared:
            _LOGGER.info("Now unavailable (%d): %s", len(appeared), ", ".join(sorted(appeared)))
        if gone:
            _LOGGER.info("Available again (%d): %s", len(gone), ", ".join(sorted(gone)))

    def _is_back(self, entity_id: str, exclusion: Exclusion) -> bool:
        """Did it really come back, rather than get removed or excluded?"""
        state = self.hass.states.get(entity_id)
        return (
            state is not None
            and state.state != STATE_UNAVAILABLE
            and not exclusion.excludes(entity_id)
        )

    # --- events -----------------------------------------------------------
    def _integration_domains(self, entity_ids: list[str]) -> list[str]:
        ent_reg = er.async_get(self.hass)
        return sorted(
            {
                registry_entry.platform
                for entity_id in entity_ids
                if (registry_entry := ent_reg.async_get(entity_id)) is not None
            }
        )

    @callback
    def _async_fire_attempt(
        self,
        *,
        operation_id: str,
        stage: int,
        trigger: str,
        now: datetime,
        entity_ids: list[str],
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """One event per recovery operation that actually ran."""
        self.hass.bus.async_fire(
            EVENT_RECOVERY_ATTEMPT,
            {
                "watchguard_entry_id": self.entry.entry_id,
                "operation_id": operation_id,
                "stage": stage,
                "trigger": trigger,
                "timestamp": now.isoformat(),
                "entity_ids": sorted(entity_ids),
                "config_entry_id": config_entry.entry_id if config_entry else None,
                "config_entry_title": config_entry.title if config_entry else None,
                "integration_domain": config_entry.domain if config_entry else None,
                "integration_domains": (
                    [config_entry.domain]
                    if config_entry
                    else self._integration_domains(entity_ids)
                ),
            },
        )

    @callback
    def _async_fire_entity_recovered(
        self, entity_id: str, tracked: Tracked, now: datetime
    ) -> None:
        """An entity we ran recovery for is available again."""
        self.hass.bus.async_fire(
            EVENT_ENTITY_RECOVERED,
            {
                "watchguard_entry_id": self.entry.entry_id,
                "entity_id": entity_id,
                "name": tracked.name,
                "unavailable_since": tracked.first_unavailable.isoformat(),
                "timestamp": now.isoformat(),
                "duration_seconds": round((now - tracked.first_unavailable).total_seconds()),
                "attempts": tracked.attempts,
                # Only stages that actually ran: stage1_at / stage2_at are also
                # set when a stage is skipped (push integration, hub threshold).
                "stages": sorted(tracked.stages_run),
                "operation_ids": list(tracked.operation_ids),
                "last_operation_id": tracked.operation_ids[-1],
            },
        )

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

        reported = [entity_id for report in domains.values() for entity_id in report.entity_ids]
        devices, without_device = self._device_reports(reported)
        return {
            "warming_up": False,
            "domains": domains,
            "total": len(reported),
            "devices": devices,
            "entities_without_device": without_device,
            "last_recovery": self.last_recovery,
        }

    def _device_reports(self, entity_ids: list[str]) -> tuple[list[DeviceReport], int]:
        """Group reported entities by their device.

        Entities without a device (templates, helpers, groups) are only counted,
        so the device total and the entity total can still be reconciled.
        """
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        by_device: dict[str, list[str]] = {}
        without_device = 0
        for entity_id in entity_ids:
            registry_entry = ent_reg.async_get(entity_id)
            device_id = registry_entry.device_id if registry_entry else None
            if device_id is None or dev_reg.async_get(device_id) is None:
                without_device += 1
                continue
            by_device.setdefault(device_id, []).append(entity_id)

        devices: list[DeviceReport] = []
        for device_id, members in by_device.items():
            device = dev_reg.async_get(device_id)
            tracked = [self._tracked[entity_id] for entity_id in members]
            watched = self._watched_device_entities(device_id)
            devices.append(
                DeviceReport(
                    device_id=device_id,
                    name=device.name_by_user or device.name or device_id,
                    entity_ids=members,
                    since=min(item.first_unavailable for item in tracked),
                    given_up=all(item.given_up for item in tracked),
                    fully_unavailable=watched <= set(members),
                )
            )
        devices.sort(key=lambda report: (report.name.casefold(), report.device_id))
        return devices, without_device

    def _watched_device_entities(self, device_id: str) -> set[str]:
        """What a device would report if all of it were down.

        Its enabled entities in a watched domain that aren't excluded and have
        a state — the yardstick for "fully unavailable".
        """
        ent_reg = er.async_get(self.hass)
        monitored = set(self.monitored_domains)
        exclusion = self._exclusion or build_exclusion(self.hass, self.options)
        return {
            entry.entity_id
            for entry in er.async_entries_for_device(ent_reg, device_id)
            if entry.domain in monitored
            and not exclusion.excludes(entry.entity_id)
            and self.hass.states.get(entry.entity_id) is not None
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

    async def async_stage1(
        self,
        entity_ids: list[str],
        now: datetime | None = None,
        trigger: str = TRIGGER_AUTOMATIC,
    ) -> None:
        """Stage 1: ask HA to poll the entities again."""
        now = now or dt_util.utcnow()
        operation_id = ulid_now()
        _LOGGER.info(
            "Stage 1 (update_entity) for %d entities: %s",
            len(entity_ids),
            ", ".join(sorted(entity_ids)),
        )
        for entity_id in entity_ids:
            if (tracked := self._tracked.get(entity_id)) is not None:
                tracked.stage1_at = now
                tracked.attempts += 1
                tracked.operation_ids.append(operation_id)
                tracked.stages_run.add(1)
        self.last_recovery = now
        self._async_fire_attempt(
            operation_id=operation_id,
            stage=1,
            trigger=trigger,
            now=now,
            entity_ids=entity_ids,
        )
        # Not blocking: a slow integration must not stall the scan cycle.
        await self.hass.services.async_call(
            "homeassistant", "update_entity", {"entity_id": entity_ids}, blocking=False
        )

    async def async_stage2(
        self,
        entity_ids: list[str],
        now: datetime | None = None,
        trigger: str = TRIGGER_AUTOMATIC,
    ) -> None:
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
            operation_id = ulid_now()
            for entity_id in affected:
                if (tracked := self._tracked.get(entity_id)) is not None:
                    tracked.stage2_at = now
                    tracked.attempts += 1
                    tracked.stage2_rounds += 1
                    tracked.operation_ids.append(operation_id)
                    tracked.stages_run.add(2)
                    self._async_check_give_up(entity_id, tracked)
            self._async_fire_attempt(
                operation_id=operation_id,
                stage=2,
                trigger=trigger,
                now=now,
                entity_ids=affected,
                config_entry=target,
            )
            self.entry.async_create_background_task(
                self.hass,
                self._async_reload(target, operation_id, trigger),
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

    async def _async_reload(
        self, target: ConfigEntry, operation_id: str, trigger: str
    ) -> None:
        """Reload wrapper — a failing reload must surface as our error, not as
        a bare "Task exception was never retrieved" from the event loop."""
        title = target.title
        error: str | None = None
        try:
            reloaded = await self.hass.config_entries.async_reload(target.entry_id)
        except Exception as err:  # noqa: BLE001 - background task, log everything
            _LOGGER.exception("Stage 2: reloading config entry %s failed", title)
            error = str(err) or type(err).__name__
        else:
            if reloaded is False:
                # async_reload reports a failed setup by returning False
                # rather than raising.
                _LOGGER.warning(
                    "Stage 2: config entry %s reloaded but did not set up again", title
                )
                error = "setup failed"
            else:
                _LOGGER.debug("Stage 2: reload of config entry %s finished", title)

        self.hass.bus.async_fire(
            EVENT_RECOVERY_RESULT,
            {
                "watchguard_entry_id": self.entry.entry_id,
                "operation_id": operation_id,
                "stage": 2,
                "trigger": trigger,
                "timestamp": dt_util.utcnow().isoformat(),
                "config_entry_id": target.entry_id,
                "config_entry_title": title,
                "integration_domain": target.domain,
                "result": RESULT_FAILED if error else RESULT_SUCCESS,
                "error": error,
            },
        )

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

        await self.async_stage1(selected, now, trigger=TRIGGER_MANUAL)
        if escalate:
            await self.async_stage2(selected, now, trigger=TRIGGER_MANUAL)
        await self.async_request_refresh()
        self._async_schedule_recovery_followups()

    @callback
    def _async_schedule_recovery_followups(self) -> None:
        """Re-scan a few times after a manual recovery.

        Recovery only *starts* things: `update_entity` is dispatched without
        waiting and a config entry reload runs as its own task. Without these
        follow-ups the dashboard keeps showing the old counts until the next
        check interval, which reads as if the button did nothing.
        """
        self._async_cancel_recovery_followups()

        async def _followup(_now: datetime) -> None:
            await self.async_refresh()

        self._followup_cancels = [
            async_call_later(self.hass, delay, _followup)
            for delay in RECOVERY_FOLLOWUP_DELAYS
        ]

    @callback
    def _async_cancel_recovery_followups(self) -> None:
        for cancel in self._followup_cancels:
            cancel()
        self._followup_cancels = []

    # --- reporting: notifications, repairs, push -------------------------
    @property
    def _report_domains(self) -> bool:
        return self.options[CONF_NOTIFY_GROUPING] != NOTIFY_GROUPING_DEVICE

    @property
    def _report_devices(self) -> bool:
        return self.options[CONF_NOTIFY_GROUPING] != NOTIFY_GROUPING_DOMAIN

    async def _async_report(self, now: datetime) -> None:
        outages = self._async_outages(now)
        device_outage = self._async_device_outage(now) if self._report_devices else DeviceOutage()
        self._async_update_notifications(outages, device_outage)
        self._async_update_repairs(outages)
        await self._async_push(outages)
        await self._async_push_devices(device_outage)

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

    def _async_device_outage(self, now: datetime) -> DeviceOutage:
        """Completely unavailable devices past the notify delay, across domains.

        A device counts once every watched entity of it is past the delay, so
        a dead Shelly with entities in three domains is one line, not three
        notifications. Partly unavailable devices are left to the domain view.
        """
        delay = timedelta(seconds=self.options[CONF_NOTIFY_DELAY])
        use_de = self.hass.config.language[:2].lower() == "de"
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)

        by_device: dict[str, list[tuple[str, Tracked]]] = {}
        without_device: list[tuple[str, Tracked]] = []
        for entity_id, tracked in sorted(self._tracked.items()):
            if now - tracked.first_unavailable < delay:
                continue
            registry_entry = ent_reg.async_get(entity_id)
            device_id = registry_entry.device_id if registry_entry else None
            if device_id is None or dev_reg.async_get(device_id) is None:
                without_device.append((entity_id, tracked))
            else:
                by_device.setdefault(device_id, []).append((entity_id, tracked))

        down: list[tuple[str, str, str, list[tuple[str, Tracked]]]] = []
        for device_id, members in by_device.items():
            if not self._watched_device_entities(device_id) <= {item for item, _ in members}:
                continue
            device = dev_reg.async_get(device_id)
            name = device.name_by_user or device.name or device_id
            down.append((name.casefold(), device_id, name, members))
        down.sort()

        outage = DeviceOutage()
        for _, device_id, name, members in down:
            outage.devices[device_id] = (name, _device_line(name, members, use_de))
        for entity_id, tracked in without_device:
            outage.entities[entity_id] = (tracked.name, _entity_line(entity_id, tracked, use_de))
        return outage

    def _device_message(self, outage: DeviceOutage, use_de: bool) -> str:
        parts = []
        if outage.devices:
            parts.append(
                ("Nicht verfügbare Geräte:" if use_de else "Unavailable devices:")
                + "\n"
                + "\n".join(line for _, line in outage.devices.values())
            )
        if outage.entities:
            parts.append(
                ("Nicht verfügbar, ohne Gerät:" if use_de else "Unavailable, without a device:")
                + "\n"
                + "\n".join(line for _, line in outage.entities.values())
            )
        return "\n\n".join(parts)

    def _async_update_notifications(
        self, outages: dict[str, Outage], device_outage: DeviceOutage
    ) -> None:
        if not self.options[CONF_NOTIFY_ENABLED]:
            self._async_clear_notifications()
            return

        use_de = self.hass.config.language[:2].lower() == "de"
        wanted: dict[str, tuple[str, str]] = {}
        if self._report_domains:
            for domain, outage in outages.items():
                intro = (
                    f"Nicht verfügbare Entities in `{domain}`:"
                    if use_de
                    else f"Unavailable entities in `{domain}`:"
                )
                wanted[f"{NOTIFICATION_ID_PREFIX}{domain}"] = (
                    f"Entity Watchguard – {domain} ({len(outage.entity_ids)})",
                    intro + "\n" + "\n".join(outage.lines),
                )
        if device_outage.names:
            counts = []
            if device_outage.devices:
                count = len(device_outage.devices)
                if use_de:
                    counts.append(f"{count} {'Gerät' if count == 1 else 'Geräte'}")
                else:
                    counts.append(f"{count} {'device' if count == 1 else 'devices'}")
            if device_outage.entities:
                counts.append(
                    f"{len(device_outage.entities)} {'ohne Gerät' if use_de else 'without device'}"
                )
            wanted[DEVICE_NOTIFICATION_ID] = (
                f"Entity Watchguard – {'Geräte' if use_de else 'devices'} ({', '.join(counts)})",
                self._device_message(device_outage, use_de),
            )

        for notification_id, (title, message) in wanted.items():
            # Re-create only on change: same notification_id replaces in place,
            # but a needless rewrite marks the notification unread again.
            if self._notifications.get(notification_id) == f"{title}\n{message}":
                continue
            persistent_notification.async_create(self.hass, message, title, notification_id)
            self._notifications[notification_id] = f"{title}\n{message}"

        for notification_id in list(self._notifications):
            if notification_id not in wanted:
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
        if not service or not self._report_domains:
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

    async def _async_push_devices(self, outage: DeviceOutage) -> None:
        """Device mode: one push per check for what went down or came back.

        Batched, so a power cut that takes out five devices sends one message
        instead of five.
        """
        service = (self.options[CONF_NOTIFY_SERVICE] or "").strip()
        if not service or not self._report_devices:
            self._pushed_devices.clear()
            return

        use_de = self.hass.config.language[:2].lower() == "de"
        current = outage.names
        new_down = outage.only(set(current) - set(self._pushed_devices))
        if new_down.names:
            await self._async_call_notify(service, self._device_message(new_down, use_de))

        back = [name for key, name in self._pushed_devices.items() if key not in current]
        if back:
            message = ("Wieder verfügbar: " if use_de else "Available again: ") + ", ".join(back)
            await self._async_call_notify(service, message)

        self._pushed_devices = current

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
        self._pushed_devices.clear()
