"""Display abstractions for monitors, windows, and a Wayland session.

The Linux provider reads DRM and input devices. It does not start a compositor.
"""

from omne.display.model import Display, FullscreenState, Monitor, Surface, Window, Workspace
from omne.display.select import diagnose_display, select_provider

__all__ = [
    "Display",
    "FullscreenState",
    "Monitor",
    "Surface",
    "Window",
    "Workspace",
    "diagnose_display",
    "select_provider",
]
