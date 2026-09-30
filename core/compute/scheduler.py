"""Reserve declared resources against a snapshot."""

from __future__ import annotations

from core.compute.allocation import AllocationDecision
from core.compute.manager import Reservation, ReservationKind, ResourceManager
from core.compute.monitor import ResourceSnapshot, SystemMonitor
from core.compute.requirements import ResourceRequirements
from core.events.bus import EventBus


class ComputeScheduler:
    """Track reservations and ask the resource manager before starting work."""

    def __init__(
        self,
        monitor: SystemMonitor,
        *,
        events: EventBus | None = None,
        manager: ResourceManager | None = None,
    ) -> None:
        self.manager = manager or ResourceManager(monitor, events=events)
        self._matched: list[tuple[str, ResourceRequirements]] = []

    def open(
        self,
        requirements: ResourceRequirements,
        *,
        owner: str,
        kind: ReservationKind,
        local: bool,
        cloud_available: bool,
        snapshot: ResourceSnapshot | None = None,
    ) -> Reservation:
        """Ask for capacity for one owner. ALLOW is already reserved."""

        return self.manager.request(
            requirements,
            owner=owner,
            kind=kind,
            local=local,
            cloud_available=cloud_available,
            snapshot=snapshot,
        )

    def run(self, reservation_id: str) -> Reservation:
        return self.manager.run(reservation_id)

    def release_id(self, reservation_id: str) -> Reservation:
        return self.manager.release(reservation_id)

    def request(
        self,
        requirements: ResourceRequirements,
        *,
        local: bool,
        cloud_available: bool,
        snapshot: ResourceSnapshot | None = None,
    ) -> AllocationDecision:
        reservation = self.open(
            requirements,
            owner="task",
            kind="task",
            local=local,
            cloud_available=cloud_available,
            snapshot=snapshot,
        )
        if reservation.decision is AllocationDecision.ALLOW:
            self._matched.append((reservation.id, requirements))
        return reservation.decision

    def release(self, requirements: ResourceRequirements) -> None:
        for index, (reservation_id, held) in enumerate(self._matched):
            if held == requirements:
                self._matched.pop(index)
                self.manager.release(reservation_id)
                return
