import path from "node:path";
import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest(async () => ({
      wrangler: { configPath: "./wrangler.jsonc" },
      miniflare: {
        bindings: {
          TEST_MIGRATIONS: await readD1Migrations(path.join(import.meta.dirname, "migrations")),
          ADMIN_TOKEN: "test-admin-token",
          GITHUB_WEBHOOK_SECRET: "test-webhook-secret",
          GITHUB_TOKEN: "test-github-token",
        },
      },
    })),
  ],
  test: {
    setupFiles: ["./test/apply-migrations.ts"],
    // One miniflare (workerd) instance at a time: parallel native-runtime
    // startups race for resources and fail intermittently on shared hosts,
    // and four workerd boots buy no wall-clock on a 4-file suite anyway.
    fileParallelism: false,
  },
});
