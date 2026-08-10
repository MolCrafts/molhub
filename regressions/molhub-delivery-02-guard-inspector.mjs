import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Run Playwright from the web package so args are not re-tokenized by npm/sh
// (unquoted `$` anchors in --grep would be expanded and split).
const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../apps/web");
const result = spawnSync(
  "npx",
  [
    "playwright",
    "test",
    "--grep",
    // Match the test title substring. Playwright greps the decorated title
    // (file › name), so anchors like `^` do not match.
    "Inspector lifecycle aborts stale work and disposes resources",
  ],
  { cwd: webRoot, shell: false, stdio: "inherit" },
);

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
