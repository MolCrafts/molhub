import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  timeout: 150_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:4173/molhub",
    colorScheme: "light",
    launchOptions: {
      args: ["--enable-webgl", "--ignore-gpu-blocklist", "--use-gl=swiftshader"],
    },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run preview -- --host 127.0.0.1 --port 4173",
    url: "http://127.0.0.1:4173/molhub/",
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
