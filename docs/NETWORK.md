# Network

Linux owns the network stack. OMNE reads it.

```text
Linux kernel and systemd-networkd
        │
        ▼
sysfs and proc
        │
        ▼
omne.network provider    ← mock session, or a Linux read
        │
        ▼
NetworkService           ← permission check, then events
        │
        ▼
OMNE Core                ← GET /network, OMNE network
        │
        ▼
OMNE Shell tray          ← the default-route interface
```

Core imports `omne.network.select`. Inspection does not run a helper, scan a radio, or write a
route. `stack_commanded` is false. There is no `POST /network`.

## What a read contains

`omne/network/model.py` defines the record:

| Field             | Meaning                                                                                      |
| ----------------- | -------------------------------------------------------------------------------------------- |
| `interfaces`      | Name, kind, operstate, IFF_UP, MAC, MTU, driver, addresses, and counters                     |
| `dns`             | Nameservers from `resolv.conf`. `dns_known` is false when that file is missing or unreadable |
| `default_route`   | The preferred default route. IPv4 wins over IPv6, then the lowest metric                     |
| `internet`        | `unknown` while a default route exists, and when the route table could not be read           |
| `networks`        | Visible Wi-Fi networks. Empty on Linux because this revision does not scan                   |
| `scan_known`      | True only after a mock scan. Linux stays false                                               |
| `gaps`            | A source that exists but could not be read                                                   |
| `stack`           | `systemd-networkd` when that unit file is present. This does not claim the daemon is running |
| `stack_commanded` | Always false                                                                                 |

A missing counter stays null. A real zero stays zero. Interface statistics are omitted from the
change signature, so a byte counter does not emit `network.changed` on every read.

`internet` is `unreachable` only when the route table was read and it has no default route. OMNE
does not ping. A default route does not become `reachable`.

## Sources

| Fact            | Linux source                                                                 |
| --------------- | ---------------------------------------------------------------------------- |
| Interfaces      | `/sys/class/net`, including loopback and bridges                             |
| Kind            | `lo` or type 772 is loopback; `wireless` or `phy80211` is Wi-Fi; else type 1 |
| Enabled         | The IFF_UP bit in `flags`. An unreadable flags file stays null               |
| Addresses       | `/proc/net/fib_trie` host LOCAL addresses, assigned by longest prefix        |
| IPv6            | `/proc/net/if_inet6`                                                         |
| Routes          | `/proc/net/route` and `/proc/net/ipv6_route`                                 |
| Wi-Fi signal    | `/proc/net/wireless` when that file exists                                   |
| DNS             | `nameserver` lines in `/etc/resolv.conf`                                     |
| Available Wi-Fi | Not read. `networks` stays empty and `scan_known` stays false                |

Loopback addresses in `127.0.0.0/8` stay on `lo`. Link-local and host scopes are kept on the
interface. The shell tray skips those scopes when it picks a display address.

## Operations

| Action     | Mock session                                                        | Linux provider                           |
| ---------- | ------------------------------------------------------------------- | ---------------------------------------- |
| inspect    | Return the in-memory session                                        | Read sysfs and proc                      |
| scan       | Reveal networks previously given to the test                        | Refused. The radio is not scanned        |
| connect    | Record an address, SSID, and gateway when the request includes them | Refused. The host stack is not commanded |
| disconnect | Clear that interface's addresses and routes                         | Refused                                  |
| enable     | Mark the interface enabled                                          | Refused                                  |
| disable    | Mark it down and clear its addresses and routes                     | Refused                                  |

The mock does not invent an address or a gateway. A password is used only to remember that the
association was secured, and the string is discarded. `WifiNetwork` has no password field.

Every mutating call goes through `NetworkService.apply` before the provider sees it. The permission
policy is:

| Tool                                                 | Grant               | Testing and development                         | Production |
| ---------------------------------------------------- | ------------------- | ----------------------------------------------- | ---------- |
| `network.scan`                                       | `network:scan`      | Allow                                           | Allow      |
| `network.connect`, `disconnect`, `enable`, `disable` | `network:configure` | Confirm. Confirmation does not apply the change | Deny       |

A missing grant is a deny. Agents are not given these grants. The Linux provider still refuses the
change after an allow, so a development machine is not reconfigured by this revision.

## Events

| Event                  | When                                                        |
| ---------------------- | ----------------------------------------------------------- |
| `network.connected`    | A mock connect recorded the interface                       |
| `network.disconnected` | A mock disconnect, or a disable of a link that was up       |
| `network.changed`      | A scan, or a later inspect whose non-counter fields changed |
| `interface.enabled`    | A mock enable, or a connect that brought the interface up   |
| `interface.disabled`   | A mock disable                                              |

The first inspect is the baseline and emits nothing. Payloads carry the interface name, an SSID, or
the changed field names. They do not carry a secret. The shell parser rejects `secret`, `password`,
`psk`, and `passphrase`.

`GET /network` and `OMNE network` return the record. They do not configure the stack.

## Future OMNE OS image

The UEFI image already matches `en*` and `eth*` and requests DHCP through systemd-networkd. That
unit remains the address and route manager. OMNE Core on the image reads the same sysfs and proc
paths and reports them on the shell tray and in `OMNE network`.

Wi-Fi on a later image is iwd for association and systemd-networkd for addressing. A scan or a
connection runs only after `network:scan` or `network:configure` is allowed, and a password stays in
the supplicant configuration rather than in OMNE events, logs, or telemetry. This revision does not
install iwd, does not scan, and does not write a network unit.
