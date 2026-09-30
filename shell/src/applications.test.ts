import assert from "node:assert/strict";
import test from "node:test";

import { applicationLabel, applicationObjective, readApplications } from "./applications.js";

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
    {
      id: "firefox",
      name: "Firefox",
      categories: ["Network", "WebBrowser"],
      state: "installed",
      windows: [],
    },
  ]);
  assert.equal(applicationObjective("Firefox"), "Open Firefox");
  assert.equal(JSON.stringify(views).includes("/usr/bin/firefox"), false);
});

test("an opened application window is labeled without its executable", () => {
  const views = readApplications({
    applications: {
      commanded: false,
      applications: [
        {
          id: "org.gnome.Files",
          name: "Files",
          categories: ["System"],
          state: "focused",
          executable: "/usr/bin/nautilus",
          windows: [{ id: "window-org.gnome.Files", title: "Files", app_id: "org.gnome.Files" }],
        },
      ],
    },
  });

  assert.equal(applicationLabel(views[0]!), "Files (Files)");
  assert.equal(JSON.stringify(views).includes("nautilus"), false);
});

test("readApplications rejects a shell command", () => {
  assert.throws(
    () => readApplications({ applications: { applications: [{ command: "sh -c true" }] } }),
    /shell command/,
  );
  assert.throws(() => readApplications({ applications: { commanded: true } }), /shell/);
});
