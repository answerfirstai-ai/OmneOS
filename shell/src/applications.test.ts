import assert from "node:assert/strict";
import test from "node:test";

import { applicationObjective, readApplications } from "./applications.js";

const payload = {
  applications: {
    commanded: false,
    applications: [
      {
        id: "firefox",
        name: "Firefox",
        categories: ["Network", "WebBrowser"],
        state: "installed",
        executable: "/usr/bin/firefox",
        commanded: false,
      },
      {
        id: "secret",
        name: "Secret",
        categories: [],
        state: "hidden",
        commanded: false,
      },
    ],
  },
};

test("readApplications lists visible applications by name", () => {
  const views = readApplications(payload);
  assert.deepEqual(views, [
    { id: "firefox", name: "Firefox", categories: ["Network", "WebBrowser"], state: "installed" },
  ]);
  assert.equal(applicationObjective("Firefox"), "Open Firefox");
  assert.equal(JSON.stringify(views).includes("/usr/bin/firefox"), false);
});

test("readApplications rejects a shell command", () => {
  assert.throws(
    () => readApplications({ applications: { applications: [{ command: "sh -c true" }] } }),
    /shell command/,
  );
  assert.throws(() => readApplications({ applications: { commanded: true } }), /shell/);
});
