"""OMNE recovery. Startup failures are explained. User data is not erased.

Safe mode keeps diagnostics, disables third-party agents and optional models,
and reduces the shell. The operating system is not reinstalled.
"""

from omne.recovery.model import RecoveryState, RecoveryStatus
from omne.recovery.select import recovery_service
from omne.recovery.service import RecoveryRefused, RecoveryService, configuration_status

__all__ = [
    "RecoveryRefused",
    "RecoveryService",
    "RecoveryState",
    "RecoveryStatus",
    "configuration_status",
    "recovery_service",
]
