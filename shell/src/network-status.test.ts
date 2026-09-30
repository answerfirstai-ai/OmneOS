import assert from "node:assert/strict";
import test from "node:test";

import { readNetworkStatus } from "./network-status.js";

const payload = {
  network: {
    observed: true,
    internet: "unknown",
    default_route: { interface: "enp0s4", destination: "default", gateway: "172.30.0.1" },
    interfaces: [
      {
        name: "lo",
        kind: "loopback",
        state: "up",
        addresses: [{ address: "127.0.0.1", scope: "host" }],
      },
      {
        name: "enp0s4",
        kind: "ethernet",
        state: "up",
        addresses: [{ address: "172.30.0.2", scope: "global" }],
      },
    ],
  },
};

test("readNetworkStatus shows the default-route interface and its address", () => {
  assert.deepEqual(readNetworkStatus(payload), { text: "enp0s4 up 172.30.0.2", state: "up" });
});

test("readNetworkStatus does not call a route reachability", () => {
  const view = readNetworkStatus({
    network: {
      ...payload.network,
      internet: "unreachable",
      default_route: null,
    },
  });
  assert.equal(view.state, "unreachable");
  assert.match(view.text, /no route/);
  assert.equal(view.text.includes("internet"), false);
});

test("readNetworkStatus stays unknown until the stack is observed", () => {
  assert.deepEqual(readNetworkStatus({ network: { observed: false, interfaces: [] } }), {
    text: "network unknown",
    state: "unknown",
  });
});

test("readNetworkStatus includes a wifi signal and rejects a secret", () => {
  const view = readNetworkStatus({
    network: {
      observed: true,
      internet: "unknown",
      default_route: null,
      interfaces: [
        {
          name: "wlan0",
          kind: "wifi",
          state: "up",
          wifi_signal_dbm: -40,
          addresses: [],
        },
      ],
    },
  });
  assert.equal(view.text, "wlan0 up -40 dBm");
  assert.throws(
    () =>
      readNetworkStatus({
        network: { ...payload.network, secret: "s3cret-psk" },
      }),
    /secret/,
  );
});
