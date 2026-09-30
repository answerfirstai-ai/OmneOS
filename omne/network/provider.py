"""Network provider interface.

Core calls this protocol. A provider does not replace the Linux network stack.
"""

from __future__ import annotations

from typing import Protocol

from omne.network.model import ApplyOutcome, NetworkRequest, NetworkState


class NetworkProvider(Protocol):
    """Inspect the stack and apply a request to the recorded session."""

    def inspect(self) -> NetworkState:
        """Return the current network record."""

    def apply(self, request: NetworkRequest) -> ApplyOutcome:
        """Update the record. Do not change the host network stack."""
