"""The four browser layers and the engine this revision does not import.

Playwright is the documented automation dependency. OMNE does not install it
and does not import it.
"""

from __future__ import annotations

from omne.browser.model import LayerSpec

ENGINE_DEPENDENCY = "playwright"
ENGINE_NOTE = (
    "Playwright is the documented browser automation engine. "
    "It is not an OMNE dependency, and this revision does not import it."
)
HOST_NOT_CONTROLLED = "host browser automation is not installed"
RESEARCH_NOT_INSTALLED = "web research retrieval is not installed"
RENDER_NOT_INSTALLED = "web rendering is not installed"

LAYER_SPECS: tuple[LayerSpec, ...] = (
    LayerSpec(
        id="application",
        capability="browser_application",
        permission="browser:launch",
        summary="The installed browser program. Launch is separate from controlling it.",
    ),
    LayerSpec(
        id="automation",
        capability="browser_automation",
        permission="browser:automate",
        summary="Scripted control of a session. It requires an automation engine.",
    ),
    LayerSpec(
        id="research",
        capability="browser_research",
        permission="browser:research",
        summary="Source lookup for research. It does not drive the browser.",
    ),
    LayerSpec(
        id="rendering",
        capability="browser_rendering",
        permission="browser:render",
        summary="A screenshot of a page. Image bytes are stored only when permitted.",
    ),
)
