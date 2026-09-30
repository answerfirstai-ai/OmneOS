"""Browser integration. The four layers do not share one permission.

The application layer names an installed browser. Automation, research, and
rendering stay behind their own grants. Playwright is documented and is not
imported here.
"""

from omne.browser.model import BrowserOutcome, BrowserState
from omne.browser.select import browser_service, select_provider
from omne.browser.service import BrowserService

__all__ = [
    "BrowserOutcome",
    "BrowserService",
    "BrowserState",
    "browser_service",
    "select_provider",
]
