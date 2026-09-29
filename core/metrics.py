"""Observed reliability counts.

Values stay at zero until an event is actually published. Latency is omitted
until a task has both a start and a completion timestamp.
"""

from __future__ import annotations

from datetime import datetime

from core.events.bus import Event


class ReliabilityLedger:
    """Count what the event bus has already reported."""

    def __init__(self) -> None:
        self.tasks_started = 0
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.verification_passed = 0
        self.verification_failed = 0
        self.retry_count = 0
        self.tool_errors = 0
        self.permission_denials = 0
        self._started: dict[str, datetime] = {}
        self._latencies: list[float] = []
        self.model_usage: dict[str, int] = {}

    def observe(self, event: Event) -> None:
        if event.type == "task.started" and event.task_id:
            self.tasks_started += 1
            self._started[event.task_id] = event.timestamp
        elif event.type == "task.completed":
            self.tasks_completed += 1
            self._record_latency(event)
        elif event.type == "task.failed":
            self.tasks_failed += 1
        elif event.type == "task.recovered":
            retry = event.payload.get("retry_count")
            if isinstance(retry, int):
                self.retry_count += 1
        elif event.type == "permission.denied":
            self.permission_denials += 1
        elif event.type == "verification.recorded":
            status = event.payload.get("status")
            if status == "PASS":
                self.verification_passed += 1
            elif status == "FAIL":
                self.verification_failed += 1
        if event.type in {"task.failed", "tool.failed"} and event.tool_id:
            self.tool_errors += 1
        if event.model_id and event.type == "task.started":
            self.model_usage[event.model_id] = self.model_usage.get(event.model_id, 0) + 1

    def snapshot(self) -> dict[str, object]:
        average: float | None = None
        if self._latencies:
            average = sum(self._latencies) / len(self._latencies)
        return {
            "tasks_started": self.tasks_started,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "verification_passed": self.verification_passed,
            "verification_failed": self.verification_failed,
            "average_latency_seconds": average,
            "retry_count": self.retry_count,
            "tool_errors": self.tool_errors,
            "permission_denials": self.permission_denials,
            "model_usage": dict(self.model_usage),
        }

    def _record_latency(self, event: Event) -> None:
        if event.task_id is None:
            return
        started = self._started.get(event.task_id)
        if started is None:
            return
        self._latencies.append((event.timestamp - started).total_seconds())
