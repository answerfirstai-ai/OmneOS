"""In-memory display provider for tests and non-Linux hosts.

The mock does not invent a GPU, a monitor, or a running session.
"""

from __future__ import annotations

import sys

from omne.display.model import Display, FullscreenState, Surface

DESKTOP_URI = "http://127.0.0.1:4173/?surface=desktop"


class MockDisplayProvider:
    """Development provider used when the Linux compositor provider is not selected."""

    def diagnose(self) -> Display:
        return Display(
            provider="mock",
            platform=sys.platform,
            linux=sys.platform.startswith("linux"),
            wayland=False,
            session="not_running",
            drm="absent",
            gpu_acceleration="unavailable",
            compositor="none",
            compositor_present=False,
            input="absent",
            monitors=[],
            windows=[],
            windows_known=True,
            workspaces=[],
            fullscreen=FullscreenState(known=True, active=False),
            surface=Surface(
                id="omne-desktop",
                role="desktop",
                active=False,
                fullscreen=False,
                uri=DESKTOP_URI,
            ),
            can_launch=False,
            missing=["graphical session"],
        )
