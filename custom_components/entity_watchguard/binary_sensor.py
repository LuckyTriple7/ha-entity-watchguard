"""Problem binary sensors — one per watched domain plus an overall one."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import DomainReport, WatchguardCoordinator
from .entity import WatchguardEntity

STATUS_WARMING_UP = "warming_up"
STATUS_OK = "ok"
STATUS_PROBLEM = "problem"

# A single integration going down can take hundreds of entities with it, and
# the full list would otherwise be written to the state machine (and the
# database) on every scan. Cap what's exposed; `count` stays exact.
MAX_LISTED = 50


def _capped(values: list[str]) -> list[str]:
    if len(values) <= MAX_LISTED:
        return values
    return values[:MAX_LISTED]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WatchguardCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = [WatchguardOverallProblem(coordinator, entry)]
    entities += [
        WatchguardDomainProblem(coordinator, entry, domain)
        for domain in coordinator.monitored_domains
    ]
    async_add_entities(entities)


def _pretty(domain: str) -> str:
    return domain.replace("_", " ").title()


class WatchguardDomainProblem(WatchguardEntity, BinarySensorEntity):
    """ON when the domain has unavailable entities past the grace period."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    # Long lists that change on every outage — keep them out of the recorder.
    _unrecorded_attributes = frozenset(
        {"unavailable_entities", "unavailable_names", "given_up_entities"}
    )

    def __init__(
        self, coordinator: WatchguardCoordinator, entry: ConfigEntry, domain: str
    ) -> None:
        super().__init__(coordinator, entry)
        self._domain = domain
        self._attr_unique_id = f"{entry.entry_id}_{domain}_problem"
        self._attr_name = _pretty(domain)

    @property
    def _report(self) -> DomainReport | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data["domains"].get(self._domain)

    @property
    def is_on(self) -> bool:
        report = self._report
        return bool(report and report.count)

    @property
    def extra_state_attributes(self) -> dict:
        report = self._report
        if self._warming_up or report is None:
            return {"status": STATUS_WARMING_UP if self._warming_up else STATUS_OK, "count": 0}
        return {
            "status": STATUS_PROBLEM if report.count else STATUS_OK,
            "count": report.count,
            "unavailable_entities": _capped(report.entity_ids),
            "unavailable_names": _capped(report.names),
            "unavailable_since": dt_util.as_local(report.since).isoformat() if report.since else None,
            "recovery_attempts": report.attempts,
            "given_up_entities": _capped(report.given_up),
            "truncated": report.count > MAX_LISTED,
        }


class WatchguardOverallProblem(WatchguardEntity, BinarySensorEntity):
    """ON when any watched domain has a problem."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _unrecorded_attributes = frozenset({"unavailable_entities"})

    def __init__(self, coordinator: WatchguardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_problem"
        self._attr_name = "Problem"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data["total"])

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data or self._warming_up:
            return {"status": STATUS_WARMING_UP if self._warming_up else STATUS_OK, "count": 0}
        domains: dict[str, DomainReport] = self.coordinator.data["domains"]
        affected = {domain: report.count for domain, report in domains.items() if report.count}
        entity_ids = [
            entity_id for report in domains.values() for entity_id in report.entity_ids
        ]
        return {
            "status": STATUS_PROBLEM if entity_ids else STATUS_OK,
            "count": self.coordinator.data["total"],
            "affected_domains": affected,
            "unavailable_entities": _capped(sorted(entity_ids)),
            "truncated": len(entity_ids) > MAX_LISTED,
        }
