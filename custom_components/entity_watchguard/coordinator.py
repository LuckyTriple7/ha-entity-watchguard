"""Scanning, recovery and notification logic for Entity Watchguard."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHECK_INTERVAL,
    CONF_GRACE_PERIOD,
    CONF_MAX_RELOADS_PER_CYCLE,
    CONF_MONITORED_DOMAINS,
    CONF_NOTIFY_DELAY,
    CONF_NOTIFY_ENABLED,
    CONF_RELOAD_COOLDOWN,
    CONF_STAGE1_DELAY,
    CONF_STAGE1_ENABLED,
    CONF_STAGE2_DELAY,
    CONF_STAGE2_ENABLED,
    CONF_STARTUP_DELAY,
    DOMAIN,
    NOTIFICATION_ID_PREFIX,
    effective_options,
)
from .filters import build_exclusion

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


@dataclass(slots=True)
class DomainReport:
    """Per-domain result handed to the entities."""

    entity_ids: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
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
        # None until HA has finished starting; see async_setup_activation().
        self._active_at: datetime | None = None

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
        self._async_update_notifications(now)
        return self._build_data(now)

    def _async_scan(self, now: datetime) -> None:
        exclusion = build_exclusion(self.hass, self.options)
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
        grace = timedelta(seconds=self.options[CONF_GRACE_PERIOD])
        domains: dict[str, DomainReport] = {domain: DomainReport() for domain in self.monitored_domains}

        for entity_id, tracked in sorted(self._tracked.items()):
            if now - tracked.first_unavailable < grace:
                continue
            report = domains.setdefault(entity_id.split(".")[0], DomainReport())
            report.entity_ids.append(entity_id)
            report.names.append(tracked.name)
            report.attempts += tracked.attempts
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
                if tracked.stage1_at is None and now - tracked.first_unavailable >= delay
            ]
            if due:
                await self.async_stage1(due, now)

        if self.options[CONF_STAGE2_ENABLED]:
            delay = timedelta(seconds=self.options[CONF_STAGE2_DELAY])
            due = [
                entity_id
                for entity_id, tracked in self._tracked.items()
                if tracked.stage2_at is None and now - tracked.first_unavailable >= delay
            ]
            if due:
                await self.async_stage2(due, now)

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
            self.entry.async_create_background_task(
                self.hass,
                self._async_reload(config_entry_id, target.title),
                f"{DOMAIN}_reload_{config_entry_id}",
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

    # --- notifications --------------------------------------------------
    def _async_update_notifications(self, now: datetime) -> None:
        if not self.options[CONF_NOTIFY_ENABLED]:
            self.async_clear_notifications()
            return

        delay = timedelta(seconds=self.options[CONF_NOTIFY_DELAY])
        use_de = self.hass.config.language[:2].lower() == "de"
        per_domain: dict[str, list[str]] = {}

        for entity_id, tracked in sorted(self._tracked.items()):
            if now - tracked.first_unavailable < delay:
                continue
            since = dt_util.as_local(tracked.first_unavailable).strftime("%d.%m.%Y %H:%M")
            label = "seit" if use_de else "since"
            per_domain.setdefault(entity_id.split(".")[0], []).append(
                f"• {tracked.name} ({entity_id}) – {label} {since}"
            )

        for domain, lines in per_domain.items():
            notification_id = f"{NOTIFICATION_ID_PREFIX}{domain}"
            if use_de:
                title = f"Entity Watchguard – {domain} ({len(lines)})"
                message = f"Nicht verfügbare Entities in `{domain}`:\n" + "\n".join(lines)
            else:
                title = f"Entity Watchguard – {domain} ({len(lines)})"
                message = f"Unavailable entities in `{domain}`:\n" + "\n".join(lines)
            # Re-create only on change: same notification_id replaces in place,
            # but a needless rewrite marks the notification unread again.
            if self._notifications.get(notification_id) == message:
                continue
            persistent_notification.async_create(self.hass, message, title, notification_id)
            self._notifications[notification_id] = message

        for notification_id in list(self._notifications):
            if notification_id.removeprefix(NOTIFICATION_ID_PREFIX) not in per_domain:
                persistent_notification.async_dismiss(self.hass, notification_id)
                del self._notifications[notification_id]

    def async_clear_notifications(self) -> None:
        for notification_id in list(self._notifications):
            persistent_notification.async_dismiss(self.hass, notification_id)
        self._notifications.clear()
