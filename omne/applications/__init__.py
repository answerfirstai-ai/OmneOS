"""Installed desktop applications. The launcher does not run a shell.

Providers report desktop metadata, processes, and windows. Launch, focus, and
close require an explicit permission and do not accept a command string.
"""

from omne.applications.model import Application, ApplicationCatalog, ApplicationReport
from omne.applications.select import application_service, select_provider
from omne.applications.service import ApplicationService

__all__ = [
    "Application",
    "ApplicationCatalog",
    "ApplicationReport",
    "ApplicationService",
    "application_service",
    "select_provider",
]
