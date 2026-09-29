import eslint from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["shell/dist/**", "shell/dist-test/**", "node_modules/**", ".venv/**"],
  },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
);
