// Package only public shell assets; runtime state and credentials never enter the artifact.
import { cp, mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const out = resolve(root, "dist/pages");
await rm(out, { recursive: true, force: true });
await mkdir(resolve(out, "desktop"), { recursive: true });
await cp(resolve(root, "shell/hub"), out, { recursive: true });
for (const name of ["index.html", "styles.css", "dist", "hub"]) {
  await cp(resolve(root, "shell", name), resolve(out, "desktop", name), { recursive: true });
}
console.log("GitHub Pages artifact: dist/pages (Core hub + existing OMNE desktop)");
