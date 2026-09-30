"""Reserve declared capacity without inventing telemetry.

A reservation moves through REQUEST, RESERVE, RUN, and RELEASE. Only RESERVE
and RUN hold capacity. A refusal leaves the ledger unchanged.
"""

from __future__ import annotations

import threading
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from core.compute.allocation import (
    AllocationDecision,
    AllocationRequest,
    ResourceLedger,
    allocate,
)
from core.compute.monitor import ResourceSnapshot, SystemMonitor
from core.compute.requirements import ResourceRequirements
from core.events.bus import EventBus

ReservationKind = Literal["task", "worker", "model"]


class ReservationState(StrEnum):
    """Lifecycle of one resource request."""

    REQUEST = "REQUEST"
    RESERVE = "RESERVE"
    RUN = "RUN"
    RELEASE = "RELEASE"


class InvalidReservation(Exception):
    """Raised when a reservation skips a lifecycle edge."""

    def __init__(
        self, reservation_id: str, current: ReservationState, proposed: ReservationState
    ) -> None:
        super().__init__(f"{reservation_id} cannot move from {current.value} to {proposed.value}")
        self.reservation_id = reservation_id
        self.current = current
        self.proposed = proposed


class Reservation(BaseModel):
    """One ask against the measured machine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    owner: str
    kind: ReservationKind
    requirements: ResourceRequirements
    local: bool
    state: ReservationState
    decision: AllocationDecision
    reason: str


_HOLDS = frozenset({ReservationState.RESERVE, ReservationState.RUN})
_TRANSITIONS: dict[ReservationState, frozenset[ReservationState]] = {
    ReservationState.REQUEST: frozenset({ReservationState.RESERVE, ReservationState.RELEASE}),
    ReservationState.RESERVE: frozenset({ReservationState.RUN, ReservationState.RELEASE}),
    ReservationState.RUN: frozenset({ReservationState.RELEASE}),
    ReservationState.RELEASE: frozenset(),
}


class ResourceManager:
    """Account for every hold against one telemetry snapshot."""

    def __init__(self, monitor: SystemMonitor, *, events: EventBus | None = None) -> None:
        self._monitor = monitor
        self._events = events
        self._reservations: dict[str, Reservation] = {}
        self._lock = threading.Lock()

    def request(
        self,
        requirements: ResourceRequirements,
        *,
        owner: str,
        kind: ReservationKind,
        local: bool,
        cloud_available: bool,
        snapshot: ResourceSnapshot | None = None,
    ) -> Reservation:
        """Record a REQUEST. ALLOW moves it to RESERVE and holds the capacity."""

        current = snapshot or self._monitor.snapshot()
        with self._lock:
            decision, reason = allocate(
                current,
                AllocationRequest(
                    requirements=requirements,
                    local=local,
                    cloud_available=cloud_available,
                ),
                held=self._held_locked(),
            )
            state = (
                ReservationState.RESERVE
                if decision is AllocationDecision.ALLOW
                else ReservationState.REQUEST
            )
            reservation = Reservation(
                id=str(uuid4()),
                owner=owner,
                kind=kind,
                requirements=requirements,
                local=local,
                state=state,
                decision=decision,
                reason=reason,
            )
            self._reservations[reservation.id] = reservation
        self._emit("compute.requested", reservation)
        if reservation.state is ReservationState.RESERVE:
            self._emit("compute.reserved", reservation)
        return reservation

    def run(self, reservation_id: str) -> Reservation:
        """Move a hold from RESERVE to RUN. The capacity stays held."""

        with self._lock:
            reservation = self._move(reservation_id, ReservationState.RUN)
        self._emit("compute.running", reservation)
        return reservation

    def release(self, reservation_id: str) -> Reservation:
        """Drop a hold. REQUEST, RESERVE, and RUN can all be released."""

        with self._lock:
            reservation = self._move(reservation_id, ReservationState.RELEASE)
        self._emit("compute.released", reservation)
        return reservation

    def get(self, reservation_id: str) -> Reservation:
        with self._lock:
            return self._require(reservation_id)

    def held(self) -> ResourceLedger:
        with self._lock:
            return self._held_locked()

    def status(self, snapshot: ResourceSnapshot | None = None) -> dict[str, object]:
        """Telemetry plus holds. Null measurements stay null."""

        current = snapshot or self._monitor.snapshot()
        with self._lock:
            ledger = self._held_locked()
            reservations = [item.model_dump(mode="json") for item in self._reservations.values()]
        return {
            "cpu": current.cpu.model_dump(),
            "memory": current.memory.model_dump(),
            "gpu": current.gpu.model_dump(),
            "disk": current.disk.model_dump(),
            "network": current.network.model_dump(),
            "thermal": current.thermal.model_dump(),
            "held": {
                "cpu_threads": ledger.cpu_threads,
                "ram_mb": ledger.ram_mb,
                "vram_mb": ledger.vram_mb,
                "disk_mb": ledger.disk_mb,
                "gpus": ledger.gpus,
            },
            "reservations": reservations,
        }

    def _held_locked(self) -> ResourceLedger:
        active = [item for item in self._reservations.values() if item.state in _HOLDS]
        return ResourceLedger(
            cpu_threads=sum(item.requirements.cpu_threads for item in active),
            ram_mb=sum(item.requirements.ram_mb for item in active),
            vram_mb=sum(item.requirements.vram_mb for item in active),
            disk_mb=sum(item.requirements.disk_mb for item in active),
            gpus=sum(
                1 for item in active if item.requirements.gpu or item.requirements.vram_mb > 0
            ),
        )

    def _move(self, reservation_id: str, proposed: ReservationState) -> Reservation:
        current = self._require(reservation_id)
        if proposed not in _TRANSITIONS[current.state]:
            raise InvalidReservation(reservation_id, current.state, proposed)
        updated = current.model_copy(update={"state": proposed})
        self._reservations[reservation_id] = updated
        return updated

    def _require(self, reservation_id: str) -> Reservation:
        try:
            return self._reservations[reservation_id]
        except KeyError as exc:
            raise KeyError(f"unknown reservation: {reservation_id}") from exc

    def _emit(self, event_type: str, reservation: Reservation) -> None:
        if self._events is None:
            return
        self._events.publish(
            event_type,
            source="compute",
            payload={
                "reservation_id": reservation.id,
                "owner": reservation.owner,
                "kind": reservation.kind,
                "state": reservation.state.value,
                "decision": reservation.decision.value,
                "reason": reservation.reason,
            },
        )
