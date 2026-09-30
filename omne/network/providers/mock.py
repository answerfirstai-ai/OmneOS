"""In-memory network session for tests and non-Linux hosts.

The mock starts disconnected. It does not invent an address, a route, or a password.
"""

from __future__ import annotations

from omne.network.model import (
    Address,
    ApplyOutcome,
    InternetState,
    NetworkEvent,
    NetworkInterface,
    NetworkRequest,
    NetworkState,
    Route,
    WifiNetwork,
)


class MockNetworkProvider:
    """A session whose changes stay inside the record."""

    def __init__(self) -> None:
        self._interfaces: list[NetworkInterface] = []
        self._dns: list[str] = []
        self._routes: list[Route] = []
        self._visible: list[WifiNetwork] = []
        self._scan_known = False

    def inspect(self) -> NetworkState:
        return self._state()

    def set_interfaces(self, interfaces: list[NetworkInterface]) -> None:
        self._interfaces = list(interfaces)

    def set_dns(self, servers: list[str]) -> None:
        self._dns = list(servers)

    def set_visible(self, networks: list[WifiNetwork]) -> None:
        self._visible = list(networks)

    def apply(self, request: NetworkRequest) -> ApplyOutcome:
        if request.action == "scan":
            return self._scan()
        if request.action == "connect":
            return self._connect(request)
        if request.action == "disconnect":
            return self._disconnect(request)
        if request.action == "enable":
            return self._enable(request)
        return self._disable(request)

    def _scan(self) -> ApplyOutcome:
        self._scan_known = True
        return self._ok(
            "scanned",
            [NetworkEvent(type="network.changed", payload={"fields": ["networks", "scan_known"]})],
        )

    def _connect(self, request: NetworkRequest) -> ApplyOutcome:
        interface = self._require(request.interface)
        if isinstance(interface, ApplyOutcome):
            return interface
        if interface.kind == "wifi" and not (request.ssid or "").strip():
            return self._refuse("request is incomplete")
        secured = True if request.secret else None
        address = (request.address or "").strip()
        addresses = list(interface.addresses)
        if address:
            addresses.append(
                Address(
                    family="ipv6" if ":" in address else "ipv4",
                    address=address,
                    prefix=request.prefix,
                    scope="global",
                )
            )
        updated = interface.model_copy(
            update={
                "enabled": True,
                "state": "up",
                "addresses": addresses,
                "connected_ssid": request.ssid if interface.kind == "wifi" else None,
                "wifi_secured": secured if interface.kind == "wifi" else None,
            }
        )
        self._replace(updated)
        if request.gateway:
            self._routes = [route for route in self._routes if route.interface != interface.name]
            self._routes.append(
                Route(
                    family="ipv4",
                    destination="default",
                    gateway=request.gateway,
                    interface=interface.name,
                    metric=0,
                )
            )
        events = [
            NetworkEvent(
                type="network.connected",
                payload={
                    "interface": interface.name,
                    "ssid": request.ssid if interface.kind == "wifi" else None,
                },
            )
        ]
        if interface.enabled is not True:
            events.append(
                NetworkEvent(type="interface.enabled", payload={"interface": interface.name})
            )
        return self._ok("connected", events)

    def _disconnect(self, request: NetworkRequest) -> ApplyOutcome:
        interface = self._require(request.interface)
        if isinstance(interface, ApplyOutcome):
            return interface
        updated = interface.model_copy(
            update={
                "addresses": [],
                "connected_ssid": None,
                "wifi_secured": None,
            }
        )
        self._replace(updated)
        self._routes = [route for route in self._routes if route.interface != interface.name]
        return self._ok(
            "disconnected",
            [
                NetworkEvent(
                    type="network.disconnected",
                    payload={"interface": interface.name},
                )
            ],
        )

    def _enable(self, request: NetworkRequest) -> ApplyOutcome:
        interface = self._require(request.interface)
        if isinstance(interface, ApplyOutcome):
            return interface
        if interface.enabled is True:
            return self._ok("enabled", [])
        self._replace(interface.model_copy(update={"enabled": True}))
        return self._ok(
            "enabled",
            [NetworkEvent(type="interface.enabled", payload={"interface": interface.name})],
        )

    def _disable(self, request: NetworkRequest) -> ApplyOutcome:
        interface = self._require(request.interface)
        if isinstance(interface, ApplyOutcome):
            return interface
        self._replace(
            interface.model_copy(
                update={
                    "enabled": False,
                    "state": "down",
                    "addresses": [],
                    "connected_ssid": None,
                    "wifi_secured": None,
                }
            )
        )
        self._routes = [route for route in self._routes if route.interface != interface.name]
        events = [NetworkEvent(type="interface.disabled", payload={"interface": interface.name})]
        if interface.state == "up" or interface.addresses or interface.connected_ssid:
            events.append(
                NetworkEvent(
                    type="network.disconnected",
                    payload={"interface": interface.name},
                )
            )
        return self._ok("disabled", events)

    def _require(self, name: str | None) -> NetworkInterface | ApplyOutcome:
        if not name:
            return self._refuse("request is incomplete")
        for interface in self._interfaces:
            if interface.name == name:
                return interface
        return self._refuse("interface is unknown")

    def _replace(self, interface: NetworkInterface) -> None:
        self._interfaces = [
            interface if item.name == interface.name else item for item in self._interfaces
        ]

    def _state(self) -> NetworkState:
        default = next((route for route in self._routes if route.destination == "default"), None)
        internet: InternetState = "unknown" if default is not None else "unreachable"
        return NetworkState(
            provider="mock",
            observed=True,
            stack="mock",
            interfaces=sorted(self._interfaces, key=lambda item: item.name),
            dns=list(self._dns),
            dns_known=True,
            default_route=default,
            internet=internet,
            networks=list(self._visible) if self._scan_known else [],
            scan_known=self._scan_known,
        )

    def _ok(self, reason: str, events: list[NetworkEvent]) -> ApplyOutcome:
        return ApplyOutcome(applied=True, reason=reason, state=self._state(), events=events)

    def _refuse(self, reason: str) -> ApplyOutcome:
        return ApplyOutcome(applied=False, reason=reason, state=self._state(), events=[])
