import assert from "node:assert/strict";
import test from "node:test";

import { fetchHealth, readCoreUrl } from "./main.js";

test("readCoreUrl defaults to the local core", () => {
  assert.equal(readCoreUrl(""), "http://127.0.0.1:8787");
});

test("readCoreUrl reads the core query parameter", () => {
  assert.equal(readCoreUrl("?core=http://localhost:9000"), "http://localhost:9000");
});

test("fetchHealth parses a successful payload", async () => {
  const health = await fetchHealth("http://127.0.0.1:8787", async () => {
    return new Response(
      JSON.stringify({
        status: "ok",
        service: "OMNE-core",
        version: "0.1.0",
        environment: "testing",
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  });
  assert.equal(health.service, "OMNE-core");
  assert.equal(health.environment, "testing");
});

test("fetchHealth reports an unreachable core", async () => {
  await assert.rejects(
    () =>
      fetchHealth("http://127.0.0.1:8787", async () => {
        throw new Error("connect ECONNREFUSED");
      }),
    /Unable to reach OMNE Core/,
  );
});

test("fetchHealth reports a non-JSON body", async () => {
  await assert.rejects(
    () =>
      fetchHealth("http://127.0.0.1:8787", async () => {
        return new Response("nope", {
          status: 200,
          headers: { "content-type": "text/plain" },
        });
      }),
    /not JSON/,
  );
});
