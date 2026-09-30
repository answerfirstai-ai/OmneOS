"""Network records for the Linux stack. OMNE does not replace it.

Providers read interfaces, addresses, DNS, and routes. Configuration stays
behind the permission system and is not applied to the host in this revision.
"""

from omne.network.model import NetworkInterface, NetworkRequest, NetworkState, WifiNetwork
from omne.network.select import network_service, select_provider
from omne.network.service import NetworkService

__all__ = [
    "NetworkInterface",
    "NetworkRequest",
    "NetworkService",
    "NetworkState",
    "WifiNetwork",
    "network_service",
    "select_provider",
]
