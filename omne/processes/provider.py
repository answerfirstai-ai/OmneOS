"""Process provider interface.

A provider does not start a shell and does not signal the host.
"""

from __future__ import annotations

from typing import Protocol

from omne.processes.model import ProcessOutcome, ProcessRequest, ProcessSnapshot


class ProcessProvider(Protocol):
    """Report the process table and record a lifecycle decision."""

    def snapshot(self) -> ProcessSnapshot:
        """Return processes. Do not include command lines."""

    def apply(self, request: ProcessRequest) -> ProcessOutcome:
        """Record start, stop, restart, or a permitted command-line read."""
