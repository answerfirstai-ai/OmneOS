import assert from "node:assert/strict";
import test from "node:test";

import { coreHealthUrl, parseHealth } from "./health.js";

const payload = {
  status: "ok",
  service: "OMNE-core",
  version: "0.1.0",
  environment: "testing",
};

test("parseHealth accepts the core document", () => {
  assert.deepEqual(parseHealth(payload), payload);
});

test("parseHealth rejects a missing field", () => {
  assert.throws(() => parseHealth({ status: "ok", service: "OMNE-core" }), /version/);
});

test("parseHealth rejects an unexpected status", () => {
  assert.throws(() => parseHealth({ ...payload, status: "starting" }), /status/);
});

test("coreHealthUrl replaces the path", () => {
  assert.equal(coreHealthUrl("http://127.0.0.1:8787/other?x=1"), "http://127.0.0.1:8787/health");
});

test("coreHealthUrl rejects an unsupported protocol", () => {
  assert.throws(() => coreHealthUrl("ftp://127.0.0.1/core"), /protocol/);
});
