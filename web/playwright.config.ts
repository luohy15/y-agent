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
  },
});
