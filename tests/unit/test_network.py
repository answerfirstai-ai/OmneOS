"""Network reads stay on the Linux stack and do not reveal passwords."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from tests.support import runtime_settings

from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionRequest
from omne.network.model import NetworkInterface, NetworkRequest, WifiNetwork
from omne.network.providers.linux import LinuxNetworkProvider
from omne.network.providers.mock import MockNetworkProvider
from omne.network.select import select_provider
from omne.network.service import NetworkService

SECRET = "s3cret-psk"


def test_mock_operations_do_not_keep_a_password() -> None:
    provider = MockNetworkProvider()
    provider.set_interfaces(
        [
            NetworkInterface(name="wlan0", kind="wifi", state="down", enabled=False),
            NetworkInterface(name="enp0s4", kind="ethernet", state="down", enabled=False),
        ]
    )
    provider.set_visible([WifiNetwork(ssid="Lab", signal_dbm=-40, secured=True)])
    scanned = provider.apply(NetworkRequest(action="scan", agent_id="coding"))

    assert scanned.applied is True
    assert scanned.state.scan_known is True
    assert scanned.state.networks[0].ssid == "Lab"
    assert SECRET not in json.dumps(scanned.state.model_dump())

    connected = provider.apply(
        NetworkRequest(
            action="connect",
            agent_id="coding",
            interface="wlan0",
            ssid="Lab",
            secret=SECRET,
            address="192.0.2.10",
            prefix=24,
            gateway="192.0.2.1",
        )
    )
    rendered = json.dumps(connected.model_dump())
    assert connected.applied is True
    assert SECRET not in rendered
    wifi = next(item for item in connected.state.interfaces if item.name == "wlan0")
    assert wifi.name == "wlan0"
    assert wifi.connected_ssid == "Lab"
    assert wifi.wifi_secured is True
    assert wifi.addresses[0].address == "192.0.2.10"
    assert connected.state.default_route is not None
    assert connected.state.default_route.gateway == "192.0.2.1"
    assert [event.type for event in connected.events] == ["network.connected", "interface.enabled"]
    assert all(SECRET not in json.dumps(event.model_dump()) for event in connected.events)

    disconnected = provider.apply(
        NetworkRequest(action="disconnect", agent_id="coding", interface="wlan0")
    )
    assert disconnected.state.default_route is None
    assert disconnected.events[0].type == "network.disconnected"
    enabled = provider.apply(NetworkRequest(action="enable", agent_id="coding", interface="enp0s4"))
    assert enabled.events[0].type == "interface.enabled"
    again = provider.apply(NetworkRequest(action="enable", agent_id="coding", interface="enp0s4"))
    assert again.applied is True
    assert again.events == []
    disabled = provider.apply(
        NetworkRequest(action="disable", agent_id="coding", interface="enp0s4")
    )
    ethernet = next(item for item in disabled.state.interfaces if item.name == "enp0s4")
    assert ethernet.enabled is False
    assert ethernet.state == "down"
    assert disabled.events[0].type == "interface.disabled"


def test_mutations_use_the_permission_system(tmp_path: Path) -> None:
    provider = MockNetworkProvider()
    provider.set_interfaces([NetworkInterface(name="enp0s4", kind="ethernet", state="up")])
    seen: list[dict[str, object]] = []

    def authorize(
        tool_id: str,
        arguments: dict[str, object],
        grants: Mapping[str, Sequence[str]],
        environment: str,
    ) -> tuple[str, str]:
        seen.append(arguments)
        result = PermissionEvaluator().evaluate(
            PermissionRequest(
                tool_id=tool_id,
                arguments=arguments,
                grants={key: list(value) for key, value in grants.items()},
                environment=environment,
                workspace_root=str(tmp_path),
            )
        )
        return result.decision.value, result.reason

    service = NetworkService(provider, authorize=authorize)
    request = NetworkRequest(
        action="connect",
        agent_id="coding",
        interface="enp0s4",
        secret=SECRET,
    )
    denied = service.apply(request, {}, "testing")
    assert denied.applied is False
    assert denied.reason.startswith("agent grant")
    assert denied.state.interfaces[0].state == "up"

    testing = service.apply(request, {"network": ["configure"]}, "testing")
    assert testing.applied is False
    assert "confirmation" in testing.reason
    assert testing.state.interfaces[0].addresses == []

    production = service.apply(request, {"network": ["configure"]}, "production")
    assert production.applied is False
    assert "denied in production" in production.reason
    assert SECRET not in json.dumps(seen)


def test_scan_is_allowed_when_granted_and_publishes_an_event(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    outcome = omne.apply_network(
        NetworkRequest(action="scan", agent_id="coding"),
        {"network": ["scan"]},
    )

    assert outcome["applied"] is True
    changed = [event for event in omne.list_events() if event.type == "network.changed"]
    assert len(changed) == 1
    assert changed[0].source == "network"
    assert SECRET not in json.dumps(outcome)


def test_linux_fixture_reports_stack_facts_without_passwords(tmp_path: Path) -> None:
    _fixture(tmp_path)
    before = (tmp_path / "sys" / "class" / "net" / "enp0s4" / "operstate").read_text(
        encoding="utf-8"
    )
    report = LinuxNetworkProvider(root=tmp_path).inspect()

    assert report.provider == "linux"
    assert report.observed is True
    assert report.stack == "systemd-networkd"
    assert report.stack_commanded is False
    assert report.scan_known is False
    assert report.networks == []
    assert report.dns == ["198.18.0.53"]
    assert report.internet == "unknown"
    assert report.default_route is not None
    assert report.default_route.gateway == "172.30.0.1"
    assert report.default_route.interface == "enp0s4"
    by_name = {item.name: item for item in report.interfaces}
    ethernet = by_name["enp0s4"]
    assert ethernet.kind == "ethernet"
    assert ethernet.state == "up"
    assert ethernet.enabled is True
    assert ethernet.driver == "virtio_net"
    assert ethernet.statistics.rx_bytes == 10
    assert ethernet.addresses[0].address == "172.30.0.2"
    assert ethernet.addresses[0].prefix == 24
    assert any(item.address.startswith("fe80::") for item in ethernet.addresses)
    wifi = by_name["wlan0"]
    assert wifi.kind == "wifi"
    assert wifi.wifi_signal_dbm == -40
    assert wifi.wifi_quality == 70
    assert wifi.enabled is False
    assert by_name["lo"].addresses[0].address == "127.0.0.1"
    assert SECRET not in json.dumps(report.model_dump())

    refused = LinuxNetworkProvider(root=tmp_path).apply(
        NetworkRequest(action="disable", agent_id="coding", interface="enp0s4", secret=SECRET)
    )
    assert refused.applied is False
    assert refused.reason == "host network stack is not commanded"
    assert refused.events == []
    assert SECRET not in json.dumps(refused.model_dump())
    after = (tmp_path / "sys" / "class" / "net" / "enp0s4" / "operstate").read_text(
        encoding="utf-8"
    )
    assert after == before


def test_missing_route_is_not_reachability(tmp_path: Path) -> None:
    net = tmp_path / "sys" / "class" / "net" / "enp0s4"
    _text(net / "operstate", "up")
    _text(net / "type", "1")
    _text(
        tmp_path / "proc" / "net" / "route",
        "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n",
    )
    report = LinuxNetworkProvider(root=tmp_path).inspect()

    assert report.default_route is None
    assert report.internet == "unreachable"
    assert report.interfaces[0].wifi_signal_dbm is None
    assert report.interfaces[0].addresses == []


def test_linux_provider_does_not_run_a_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess")

    monkeypatch.setattr("subprocess.run", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    source = Path(sys.modules["omne.network.providers.linux"].__file__ or "")
    text = source.read_text(encoding="utf-8")
    assert "subprocess" not in text
    assert "write_text" not in text
    assert "networkctl" not in text
    assert "iwctl" not in text
    LinuxNetworkProvider(root=tmp_path).inspect()
    scanned = LinuxNetworkProvider(root=tmp_path).apply(
        NetworkRequest(action="scan", agent_id="coding")
    )
    assert scanned.applied is False
    assert scanned.reason == "the host radio is not scanned"


def test_testing_api_is_a_read_only_mock(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/network", {})

    assert status.value == 200
    network = body["network"]
    assert isinstance(network, dict)
    assert network["provider"] == "mock"
    assert network["observed"] is True
    assert network["stack_commanded"] is False
    assert network["interfaces"] == []
    assert network["internet"] == "unreachable"
    posted, payload = route_post(omne, "/network", {"action": "disconnect"})
    assert posted.value == 404
    assert payload["error"] == "not_found"


def test_testing_selects_mock_even_on_linux(tmp_path: Path) -> None:
    assert isinstance(select_provider("testing"), MockNetworkProvider)
    if sys.platform.startswith("linux"):
        provider = select_provider("development", root=tmp_path)
        assert isinstance(provider, LinuxNetworkProvider)
        assert provider.inspect().interfaces == []


def _fixture(root: Path) -> None:
    ethernet = root / "sys" / "class" / "net" / "enp0s4"
    _text(ethernet / "operstate", "up")
    _text(ethernet / "type", "1")
    _text(ethernet / "flags", "0x1003")
    _text(ethernet / "address", "02:00:00:00:00:01")
    _text(ethernet / "mtu", "1500")
    _text(ethernet / "statistics" / "rx_bytes", "10")
    _text(ethernet / "statistics" / "tx_bytes", "4")
    _link(ethernet / "device" / "driver", "virtio_net")
    loop = root / "sys" / "class" / "net" / "lo"
    _text(loop / "operstate", "up")
    _text(loop / "type", "772")
    _text(loop / "flags", "0x9")
    _text(loop / "address", "00:00:00:00:00:00")
    wifi = root / "sys" / "class" / "net" / "wlan0"
    _text(wifi / "operstate", "down")
    _text(wifi / "type", "1")
    _text(wifi / "flags", "0x1002")
    (wifi / "wireless").mkdir(parents=True, exist_ok=True)
    _text(
        root / "proc" / "net" / "route",
        "\n".join(
            [
                "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT",
                "enp0s4\t00000000\t01001EAC\t0003\t0\t0\t0\t00000000\t0\t0\t0",
                "enp0s4\t00001EAC\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0",
                "",
            ]
        ),
    )
    _text(
        root / "proc" / "net" / "fib_trie",
        "\n".join(
            [
                "Local:",
                "  +-- 0.0.0.0/0 2 0 2",
                "     |-- 127.0.0.1",
                "        /32 host LOCAL",
                "     |-- 172.30.0.2",
                "        /32 host LOCAL",
                "",
            ]
        ),
    )
    _text(
        root / "proc" / "net" / "if_inet6",
        "fe80000000000000802b38fffe3dbcd0 02 40 20 80       enp0s4\n",
    )
    _text(
        root / "proc" / "net" / "wireless",
        "Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n"
        " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n"
        " wlan0: 0000   70.  -40.  -256        0      0      0      0      0        0\n",
    )
    _text(root / "etc" / "resolv.conf", "nameserver 198.18.0.53\n")
    _text(root / "lib" / "systemd" / "system" / "systemd-networkd.service", "[Service]\n")
    _text(
        root / "etc" / "wpa_supplicant" / "wpa_supplicant.conf",
        f'network={{ssid="Lab" psk="{SECRET}"}}\n',
    )


def _text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _link(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(f"../../../../bus/pci/drivers/{name}")
