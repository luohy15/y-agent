import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:5192",
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: "npx vite --port 5192 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:5192",
    reuseExistingServer: false,
    timeout: 60_000,
    // web/.env.local is shared across worktrees and usually points VITE_API_URL
    // at the deployed API. Pin the test build to the local dev origin so an
    // interception the suite forgot fails against 127.0.0.1 instead of
    // reaching production (an existing env var wins over .env files in Vite).
    env: { VITE_API_URL: "http://127.0.0.1:5192" },
  },
});
