import eslint from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["shell/dist/**", "shell/dist-test/**", "node_modules/**", ".venv/**", "dist/**"],
  },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["scripts/development/build-pages.mjs"],
    languageOptions: { globals: { console: "readonly" } },
  },
  {
    files: ["shell/hub/*.js"],
    languageOptions: {
      globals: Object.fromEntries(
        [
          "document",
          "window",
          "localStorage",
          "sessionStorage",
          "location",
          "matchMedia",
          "clearTimeout",
          "setTimeout",
          "setInterval",
          "fetch",
          "AbortSignal",
          "URL",
          "Blob",
          "Option",
          "innerWidth",
          "innerHeight",
          "devicePixelRatio",
          "requestAnimationFrame",
        ].map((name) => [name, "readonly"]),
      ),
    },
  },
);
