import { defineConfig } from "@playwright/test";

// The stack (Postgres, API, static server) must be up: `docker compose up -d --build --wait`,
// with API_PORT matching the value exported here. `make e2e` checks that before running.
export default defineConfig({
  testDir: "./tests",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1, // the tests share one database
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.STATIC_URL ?? "http://localhost:8080",
    browserName: "chromium",
    headless: true,
    viewport: { width: 1280, height: 800 },
  },
});
