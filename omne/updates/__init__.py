"""OMNE's update layer over the distribution's packages.

Ubuntu apt and dpkg remain the package tools. This package checks signed
catalogs, records history, and prepares a pending slot. It does not install
onto the development host.
"""

from omne.updates.model import UpdatePhase, UpdateStatus
from omne.updates.select import update_service
from omne.updates.service import UpdateRejected, UpdateService

__all__ = [
    "UpdatePhase",
    "UpdateRejected",
    "UpdateService",
    "UpdateStatus",
    "update_service",
]
