"""Read the Linux network stack without configuring it.

systemd-networkd remains the address and route manager. This module reads
sysfs and proc. It does not start a helper, scan a radio, or write a sysctl,
a route, or a link flag.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from omne.network.model import (
    Address,
    ApplyOutcome,
    InterfaceKind,
    InterfaceStats,
    InternetState,
    NetworkInterface,
    NetworkRequest,
    NetworkState,
    Route,
    StackName,
)

HOST_UNCHANGED = "host network stack is not commanded"
RADIO_NOT_SCANNED = "the host radio is not scanned"
_IPV6_SCOPE = {0: "global", 0x10: "host", 0x20: "link", 0x40: "site"}


class LinuxNetworkProvider:
    """Report interfaces, addresses, DNS, and routes from one filesystem root."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root if root is not None else Path("/")

    def inspect(self) -> NetworkState:
        if not self._root.is_dir():
            return NetworkState(
                provider="linux",
                observed=False,
                stack="unknown",
                dns_known=False,
                internet="unknown",
                scan_known=False,
                gaps=["linux"],
            )
        gaps: list[str] = []
        interfaces, iface_gap = _interfaces(self._root)
        if iface_gap:
            gaps.append(iface_gap)
        routes, route_gap = _routes(self._root)
        if route_gap:
            gaps.append(route_gap)
        _assign_addresses(
            interfaces, routes, _local_ipv4(_optional(self._root / "proc" / "net" / "fib_trie"))
        )
        _assign_ipv6(interfaces, _ipv6_addresses(self._root))
        signals = _wireless(self._root)
        interfaces = [_with_signal(item, signals.get(item.name)) for item in interfaces]
        dns, dns_known, dns_gap = _dns(self._root)
        if dns_gap:
            gaps.append(dns_gap)
        default = _default_route(routes)
        if route_gap:
            internet: InternetState = "unknown"
        elif default is None:
            internet = "unreachable"
        else:
            internet = "unknown"
        return NetworkState(
            provider="linux",
            observed=True,
            stack=_stack(self._root),
            interfaces=sorted(interfaces, key=lambda item: item.name),
            dns=dns,
            dns_known=dns_known,
            default_route=default,
            internet=internet,
            networks=[],
            scan_known=False,
            gaps=sorted(set(gaps)),
        )

    def apply(self, request: NetworkRequest) -> ApplyOutcome:
        state = self.inspect()
        reason = RADIO_NOT_SCANNED if request.action == "scan" else HOST_UNCHANGED
        return ApplyOutcome(applied=False, reason=reason, state=state, events=[])


def _interfaces(root: Path) -> tuple[list[NetworkInterface], str | None]:
    directory = root / "sys" / "class" / "net"
    listed = _list_dir(directory)
    if listed is None:
        return [], "interfaces"
    found: list[NetworkInterface] = []
    for path in listed:
        kind = _kind(path)
        flags = _optional(path / "flags")
        enabled = _iff_up(flags) if flags is not None else None
        found.append(
            NetworkInterface(
                name=path.name,
                kind=kind,
                state=_optional(path / "operstate") or "unknown",
                enabled=enabled,
                mac=_optional(path / "address"),
                mtu=_int_text(_optional(path / "mtu")),
                driver=_driver(path / "device"),
                statistics=_stats(path / "statistics"),
            )
        )
    return found, None


def _kind(path: Path) -> InterfaceKind:
    medium = _optional(path / "type")
    if path.name == "lo" or medium == "772":
        return "loopback"
    if (path / "wireless").exists() or (path / "phy80211").exists():
        return "wifi"
    if (path / "bridge").exists():
        return "bridge"
    if medium == "1":
        return "ethernet"
    return "other"


def _stats(path: Path) -> InterfaceStats:
    return InterfaceStats(
        rx_bytes=_int_text(_optional(path / "rx_bytes")),
        tx_bytes=_int_text(_optional(path / "tx_bytes")),
        rx_packets=_int_text(_optional(path / "rx_packets")),
        tx_packets=_int_text(_optional(path / "tx_packets")),
        rx_errors=_int_text(_optional(path / "rx_errors")),
        tx_errors=_int_text(_optional(path / "tx_errors")),
    )


def _routes(root: Path) -> tuple[list[Route], str | None]:
    path = root / "proc" / "net" / "route"
    if not path.exists():
        return _ipv6_routes(root), None
    text = _optional(path)
    if text is None:
        return [], "route"
    routes = _parse_ipv4_routes(text)
    routes.extend(_ipv6_routes(root))
    return routes, None


def _parse_ipv4_routes(text: str) -> list[Route]:
    routes: list[Route] = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 8:
            continue
        interface, destination, gateway, _flags, _ref, _use, metric, mask = parts[:8]
        prefix = _prefix_len(mask)
        dest_ip = _ipv4_le(destination)
        gateway_ip = _ipv4_le(gateway)
        if dest_ip is None or (gateway != "00000000" and gateway_ip is None):
            continue
        if destination == "00000000":
            routes.append(
                Route(
                    family="ipv4",
                    destination="default",
                    gateway=None if gateway == "00000000" else gateway_ip,
                    interface=interface,
                    metric=_int_text(metric),
                )
            )
            continue
        routes.append(
            Route(
                family="ipv4",
                destination=f"{dest_ip}/{prefix}",
                gateway=None if gateway == "00000000" else gateway_ip,
                interface=interface,
                metric=_int_text(metric),
            )
        )
    return routes


def _ipv6_routes(root: Path) -> list[Route]:
    text = _optional(root / "proc" / "net" / "ipv6_route")
    if text is None:
        return []
    routes: list[Route] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 10 or parts[0] != "0" * 32 or parts[1] != "00":
            continue
        if parts[4] == "0" * 32:
            continue
        try:
            metric = int(parts[5], 16)
        except ValueError:
            continue
        routes.append(
            Route(
                family="ipv6",
                destination="default",
                gateway=_format_ipv6(parts[4]),
                interface=parts[9],
                metric=metric,
            )
        )
    return routes


def _default_route(routes: list[Route]) -> Route | None:
    defaults = [route for route in routes if route.destination == "default"]
    if not defaults:
        return None
    ipv4 = [route for route in defaults if route.family == "ipv4"]
    chosen = ipv4 or defaults
    return min(chosen, key=lambda route: route.metric if route.metric is not None else 0)


def _assign_addresses(
    interfaces: list[NetworkInterface], routes: list[Route], addresses: list[str]
) -> None:
    by_name = {item.name: item for item in interfaces}
    for address in addresses:
        interface_name, prefix = _address_owner(address, routes, by_name)
        if interface_name is None:
            continue
        current = by_name[interface_name]
        updated = current.model_copy(
            update={
                "addresses": [
                    *current.addresses,
                    Address(
                        family="ipv4", address=address, prefix=prefix, scope=_v4_scope(address)
                    ),
                ]
            }
        )
        by_name[interface_name] = updated
    interfaces[:] = list(by_name.values())


def _address_owner(
    address: str, routes: list[Route], interfaces: dict[str, NetworkInterface]
) -> tuple[str | None, int | None]:
    if address.startswith("127.") and "lo" in interfaces:
        return "lo", 8
    ip = _parse_ipv4(address)
    if ip is None:
        return None, None
    best: tuple[int, str] | None = None
    for route in routes:
        if route.family != "ipv4" or route.destination == "default" or "/" not in route.destination:
            continue
        network, _, prefix_text = route.destination.partition("/")
        prefix = _int_text(prefix_text)
        network_ip = _parse_ipv4(network)
        if prefix is None or network_ip is None or prefix == 0:
            continue
        if _masked(ip, prefix) == _masked(network_ip, prefix) and (
            best is None or prefix > best[0]
        ):
            best = (prefix, route.interface)
    if best is None:
        return None, None
    return best[1], best[0]


def _assign_ipv6(
    interfaces: list[NetworkInterface], addresses: list[tuple[str, str, int, str | None]]
) -> None:
    by_name = {item.name: item for item in interfaces}
    for name, address, prefix, scope in addresses:
        current = by_name.get(name)
        if current is None:
            continue
        by_name[name] = current.model_copy(
            update={
                "addresses": [
                    *current.addresses,
                    Address(family="ipv6", address=address, prefix=prefix, scope=scope),
                ]
            }
        )
    interfaces[:] = list(by_name.values())


def _ipv6_addresses(root: Path) -> list[tuple[str, str, int, str | None]]:
    text = _optional(root / "proc" / "net" / "if_inet6")
    if text is None:
        return []
    found: list[tuple[str, str, int, str | None]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            prefix = int(parts[2], 16)
            scope_bits = int(parts[3], 16)
        except ValueError:
            continue
        found.append((parts[5], _format_ipv6(parts[0]), prefix, _IPV6_SCOPE.get(scope_bits)))
    return found


def _local_ipv4(text: str | None) -> list[str]:
    if text is None or "Local:" not in text:
        return []
    body = text.split("Local:", 1)[1]
    found: list[str] = []
    pending: str | None = None
    for line in body.splitlines():
        stripped = line.strip()
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)\s*$", stripped)
        if match and "/" not in stripped:
            pending = match.group(1)
            continue
        if pending and "/32 host LOCAL" in stripped:
            found.append(pending)
        pending = None
    return found


def _wireless(root: Path) -> dict[str, tuple[int | None, int | None]]:
    text = _optional(root / "proc" / "net" / "wireless")
    if text is None:
        return {}
    found: dict[str, tuple[int | None, int | None]] = {}
    for line in text.splitlines():
        if ":" not in line or line.lower().startswith("inter"):
            continue
        name, rest = line.split(":", 1)
        parts = rest.split()
        if len(parts) < 3:
            continue
        found[name.strip()] = (_int_text(parts[1].rstrip(".")), _int_text(parts[2].rstrip(".")))
    return found


def _with_signal(
    interface: NetworkInterface, signal: tuple[int | None, int | None] | None
) -> NetworkInterface:
    if signal is None:
        return interface
    quality, level = signal
    return interface.model_copy(update={"wifi_quality": quality, "wifi_signal_dbm": level})


def _dns(root: Path) -> tuple[list[str], bool, str | None]:
    path = root / "etc" / "resolv.conf"
    if not path.exists():
        return [], False, None
    text = _optional(path)
    if text is None:
        return [], False, "dns"
    servers: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("nameserver"):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            servers.append(parts[1])
    return servers, True, None


def _stack(root: Path) -> StackName:
    for relative in (
        Path("lib/systemd/system/systemd-networkd.service"),
        Path("usr/lib/systemd/system/systemd-networkd.service"),
    ):
        if (root / relative).is_file():
            return "systemd-networkd"
    return "unknown"


def _driver(path: Path) -> str | None:
    link = path / "driver"
    try:
        target = os.readlink(link)
    except OSError:
        return None
    name = Path(target).name
    return name or None


def _iff_up(flags: str) -> bool | None:
    try:
        return bool(int(flags, 0) & 1)
    except ValueError:
        return None


def _list_dir(path: Path) -> list[Path] | None:
    if not path.exists():
        return []
    if not path.is_dir():
        return []
    try:
        return sorted(path.iterdir(), key=lambda item: item.name)
    except OSError:
        return None


def _optional(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text or None


def _int_text(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text, 0)
    except ValueError:
        return None


def _ipv4_le(hex_word: str) -> str | None:
    try:
        raw = int(hex_word, 16)
    except ValueError:
        return None
    return ".".join(str((raw >> (8 * index)) & 0xFF) for index in range(4))


def _prefix_len(mask_hex: str) -> int:
    try:
        return bin(int(mask_hex, 16)).count("1")
    except ValueError:
        return 0


def _parse_ipv4(text: str) -> int | None:
    parts = text.split(".")
    if len(parts) != 4:
        return None
    value = 0
    for part in parts:
        if not part.isdigit():
            return None
        number = int(part)
        if number > 255:
            return None
        value = (value << 8) | number
    return value


def _masked(value: int, prefix: int) -> int:
    if prefix <= 0:
        return 0
    if prefix >= 32:
        return value
    return value & (0xFFFFFFFF << (32 - prefix))


def _v4_scope(address: str) -> str:
    if address.startswith("127."):
        return "host"
    return "global"


def _format_ipv6(hex_addr: str) -> str:
    padded = hex_addr.strip().lower()
    if len(padded) != 32 or any(character not in "0123456789abcdef" for character in padded):
        return hex_addr.strip()
    groups = [format(int(padded[index : index + 4], 16), "x") for index in range(0, 32, 4)]
    best_start = -1
    best_len = 0
    index = 0
    while index < len(groups):
        if groups[index] != "0":
            index += 1
            continue
        end = index
        while end < len(groups) and groups[end] == "0":
            end += 1
        if end - index > best_len:
            best_start = index
            best_len = end - index
        index = end
    if best_len < 2:
        return ":".join(groups)
    head = ":".join(groups[:best_start])
    tail = ":".join(groups[best_start + best_len :])
    if not head and not tail:
        return "::"
    if not head:
        return f"::{tail}"
    if not tail:
        return f"{head}::"
    return f"{head}::{tail}"
