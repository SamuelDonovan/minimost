import js from "@eslint/js";
import globals from "globals";

// Flat config for the browser-side JavaScript under src/minimost/static.
//
// These files are plain `<script>` includes loaded into a single shared global
// scope (not ES modules), and many functions are invoked from inline handlers
// in the Jinja templates. Because of that, two of the recommended rules produce
// only false positives here and are disabled:
//   * no-undef       — symbols defined in a sibling script file (or provided by
//                      the browser) look "undefined" when each file is linted in
//                      isolation.
//   * no-unused-vars — top-level functions/vars are the cross-file/inline-handler
//                      API surface, so they read as "unused" within their file.
// Every other recommended rule (no-useless-assignment, no-dupe-keys,
// no-unreachable, …) stays on and still catches real bugs.
export default [
  {
    ignores: ["node_modules/", "coverage/", "**/*.min.js"],
  },
  js.configs.recommended,
  {
    files: ["src/minimost/static/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "script",
      globals: { ...globals.browser },
    },
    rules: {
      "no-undef": "off",
      "no-unused-vars": "off",
    },
  },
  {
    files: ["src/minimost/static/sw.js"],
    languageOptions: {
      globals: { ...globals.serviceworker },
    },
  },
];
