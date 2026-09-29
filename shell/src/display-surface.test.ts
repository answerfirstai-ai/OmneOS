import assert from "node:assert/strict";
import test from "node:test";

import { DESKTOP_SURFACE_URI, desktopSurfaceUrl } from "./display-surface.js";

test("the desktop surface is the existing shell with a surface query", () => {
  assert.equal(DESKTOP_SURFACE_URI, "http://127.0.0.1:4173/?surface=desktop");
  assert.equal(
    desktopSurfaceUrl("http://127.0.0.1:4173/"),
    "http://127.0.0.1:4173/?surface=desktop",
  );
});
