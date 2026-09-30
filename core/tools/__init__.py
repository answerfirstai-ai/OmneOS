"""Permission-gated tools."""

from typing import cast

from core.tools.applications import application_tools
from core.tools.base import Tool, ToolResult
from core.tools.browser import browser_tools
from core.tools.filesystem import filesystem_tools
from core.tools.gateway import ToolGateway
from core.tools.git import git_tools
from core.tools.observers import observer_tools
from core.tools.processes import process_tools
from core.tools.registry import ToolRegistry
from core.tools.system import system_tools
from omne.applications.select import application_service
from omne.applications.service import ApplicationService
from omne.audio.select import audio_service
from omne.audio.service import AudioService
from omne.browser.select import browser_service
from omne.browser.service import BrowserService
from omne.display.provider import DisplayProvider
from omne.display.select import select_provider as select_display
from omne.hardware.select import hardware_service
from omne.hardware.service import HardwareService
from omne.input.select import input_service
from omne.input.service import InputService
from omne.network.select import network_service
from omne.network.service import NetworkService
from omne.processes.select import process_service
from omne.processes.service import ProcessService
from omne.storage.select import storage_service
from omne.storage.service import StorageService

__all__ = [
    "ToolGateway",
    "ToolRegistry",
    "ToolResult",
    "application_tools",
    "browser_tools",
    "build_registry",
    "filesystem_tools",
    "git_tools",
    "process_tools",
    "system_tools",
]


def build_registry(
    *,
    browser_command: str = "",
    applications: ApplicationService | None = None,
    browser: BrowserService | None = None,
    processes: ProcessService | None = None,
    environment: str = "testing",
    network: NetworkService | None = None,
    audio: AudioService | None = None,
    hardware: HardwareService | None = None,
    storage: StorageService | None = None,
    display: DisplayProvider | None = None,
    controls: InputService | None = None,
) -> ToolRegistry:
    """Register the built-in tools."""

    registry = ToolRegistry()
    catalog = applications if applications is not None else application_service(environment)
    browsers = browser if browser is not None else browser_service(environment)
    table = processes if processes is not None else process_service(environment)
    for tool in (
        *filesystem_tools(),
        *process_tools(table),
        *system_tools(),
        *git_tools(),
        *browser_tools(browser_command, service=browsers),
        *application_tools(catalog),
        *observer_tools(
            environment=environment,
            network=network if network is not None else network_service(environment),
            audio=audio if audio is not None else audio_service(environment),
            hardware=hardware if hardware is not None else hardware_service(environment),
            storage=storage if storage is not None else storage_service(environment),
            display=display if display is not None else select_display(environment),
            controls=controls if controls is not None else input_service(environment),
        ),
    ):
        registry.register(cast(Tool, tool))
    from core.tools.terminal import TerminalTool

    registry.register(TerminalTool())
    return registry
