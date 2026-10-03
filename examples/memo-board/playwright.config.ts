import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 20_000,
  retries: 0,
  workers: 1,
  reporter: "line",
  use: { baseURL: "http://localhost:4183" },
  webServer: {
    command: "node server.js",
    port: 4183,
    reuseExistingServer: true,
    timeout: 15_000,
  },
  projects: [
    {
      name: "mobile",
      use: { browserName: "chromium", viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true },
    },
  ],
});
