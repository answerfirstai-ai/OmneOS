import assert from "node:assert/strict";
import test from "node:test";

import {
  bootSurface,
  nextSetupStep,
  previousSetupStep,
  readTheme,
  stageDependencies,
  surfaceAfterUnlock,
  themeFromDraft,
  themeVariables,
  type SetupDraft,
} from "./firstboot.js";

const DRAFT: SetupDraft = {
  name: "Ada",
  color: "tide",
  type: "editorial",
  wallpaper: "night",
  password: "correct-horse",
  confirm: "correct-horse",
};

test("a missing record stays on setup and a finished record does not", () => {
  assert.equal(bootSurface(null), "hold");
  assert.equal(bootSurface({ complete: false, gate: "setup", name: "" }), "setup");
  assert.equal(bootSurface({ complete: true, gate: "password", name: "Ada" }), "password");
  assert.equal(bootSurface({ complete: true, gate: "setup", name: "Ada" }), "password");
});

test("the password gate opens the desktop only when the password matches", () => {
  assert.equal(surfaceAfterUnlock(false), "password");
  assert.equal(surfaceAfterUnlock(true), "desktop");
});

test("setup steps collect a name, a look, and a password", () => {
  assert.equal(nextSetupStep("welcome", DRAFT).step, "name");
  assert.equal(nextSetupStep("name", { ...DRAFT, name: " " }).error, "Enter a name");
  assert.equal(nextSetupStep("name", DRAFT).step, "look");
  assert.equal(nextSetupStep("look", DRAFT).step, "password");
  assert.equal(
    nextSetupStep("password", { ...DRAFT, password: "short", confirm: "short" }).error,
    "Use at least 8 characters",
  );
  assert.equal(
    nextSetupStep("password", { ...DRAFT, confirm: "other-password" }).error,
    "Those passwords do not match",
  );
  assert.equal(nextSetupStep("password", DRAFT).step, "finish");
  assert.equal(previousSetupStep("password"), "look");
  assert.equal(previousSetupStep("welcome"), "welcome");
});

test("dependency rows are staged and do not pretend to fetch weights", () => {
  const welcome = stageDependencies("welcome");
  assert.equal(welcome[0]?.state, "staged");
  assert.equal(welcome[3]?.state, "waiting");
  assert.equal(welcome[3]?.label, "Model catalog");
  const done = stageDependencies("password");
  assert.equal(
    done.every((item) => item.state === "staged"),
    true,
  );
});

test("theme data sets color, type, and wallpaper and refuses a path", () => {
  const theme = themeFromDraft(DRAFT);
  const variables = themeVariables(theme);
  assert.ok(variables);
  assert.equal(variables["--accent"], "#7eb6d6");
  assert.equal(variables["--type"], '"Iowan Old Style", Palatino, "Palatino Linotype", serif');
  assert.match(variables["--wallpaper"] ?? "", /^linear-gradient/);
  assert.equal(readTheme(theme)?.colors.desktop, "#10202c");

  const bootPath = {
    ...theme,
    wallpaper: "/boot/grub.cfg",
  };
  assert.equal(themeVariables(bootPath), null);
  assert.equal(readTheme(bootPath), null);
  const packagePath = {
    ...theme,
    wallpaper: "url(/usr/share/omne/shell/styles.css)",
  };
  assert.equal(themeVariables(packagePath), null);
  const unitPath = {
    ...theme,
    type: "/etc/systemd/system/omne-core.service",
  };
  assert.equal(themeVariables(unitPath), null);
});
