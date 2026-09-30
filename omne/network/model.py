"""Network records read from the Linux stack.

Passwords are not a field. A missing measurement stays null.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderName = Literal["mock", "linux"]
StackName = Literal["mock", "systemd-networkd", "unknown"]
InterfaceKind = Literal["ethernet", "wifi", "loopback", "bridge", "other"]
AddressFamily = Literal["ipv4", "ipv6"]
InternetState = Literal["unknown", "unreachable", "reachable"]
NetworkAction = Literal["scan", "connect", "disconnect", "enable", "disable"]
NetworkEventType = Literal[
    "network.connected",
    "network.disconnected",
    "network.changed",
    "interface.enabled",
    "interface.disabled",
]


class Address(BaseModel):
    """One address the kernel listed for an interface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    family: AddressFamily
    address: str = Field(min_length=1)
    prefix: int | None = None
    scope: str | None = None


class InterfaceStats(BaseModel):
    """Counters from sysfs. A missing file stays null."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rx_bytes: int | None = None
    tx_bytes: int | None = None
    rx_packets: int | None = None
    tx_packets: int | None = None
    rx_errors: int | None = None
    tx_errors: int | None = None


class NetworkInterface(BaseModel):
    """One interface from the kernel or the mock session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    kind: InterfaceKind
    state: str = Field(min_length=1)
    enabled: bool | None = None
    mac: str | None = None
    mtu: int | None = None
    driver: str | None = None
    addresses: list[Address] = Field(default_factory=list)
    statistics: InterfaceStats = Field(default_factory=InterfaceStats)
    wifi_signal_dbm: int | None = None
    wifi_quality: int | None = None
    connected_ssid: str | None = None
    wifi_secured: bool | None = None


class Route(BaseModel):
    """One route. The default route uses destination ``default``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    family: AddressFamily
    destination: str = Field(min_length=1)
    gateway: str | None = None
    interface: str = Field(min_length=1)
    metric: int | None = None


class WifiNetwork(BaseModel):
    """A visible network. The record has no password field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ssid: str = Field(min_length=1)
    signal_dbm: int | None = None
    secured: bool | None = None


class NetworkState(BaseModel):
    """One read of the Linux network stack."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    observed: bool
    stack: StackName
    stack_commanded: bool = False
    interfaces: list[NetworkInterface] = Field(default_factory=list)
    dns: list[str] = Field(default_factory=list)
    dns_known: bool
    default_route: Route | None = None
    internet: InternetState
    networks: list[WifiNetwork] = Field(default_factory=list)
    scan_known: bool
    gaps: list[str] = Field(default_factory=list)

    @field_validator("stack_commanded")
    @classmethod
    def _not_commanded(cls, value: bool) -> bool:
        if value:
            raise ValueError("stack_commanded must be false")
        return value


class NetworkRequest(BaseModel):
    """A requested network change. ``secret`` is never copied into state or events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: NetworkAction
    agent_id: str = Field(min_length=1)
    interface: str | None = None
    ssid: str | None = None
    secret: str | None = None
    address: str | None = None
    prefix: int | None = None
    gateway: str | None = None

    def public_arguments(self) -> dict[str, object]:
        """Arguments safe to hand to the permission policy and the audit log."""

        payload = self.model_dump(exclude={"secret"})
        return {key: value for key, value in payload.items() if value is not None}


class NetworkEvent(BaseModel):
    """One network event. Payloads do not carry secrets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: NetworkEventType
    payload: dict[str, Any] = Field(default_factory=dict)


class ApplyOutcome(BaseModel):
    """Whether a request changed the recorded network session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    applied: bool
    reason: str
    state: NetworkState
    events: list[NetworkEvent] = Field(default_factory=list)
