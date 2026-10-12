import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  // web/.env.local is shared across worktrees and holds dev-session values;
  // Vite loads it in every mode, so a dev API base can otherwise be compiled
  // into a production bundle and shipped (todo 2923). Absent VITE_API_URL is
  // the correct production path (web/src/api.ts falls back to
  // window.location.origin); only a *present* localhost value is the defect.
  const apiUrl = loadEnv(mode, __dirname, "VITE_").VITE_API_URL;
  if (mode === "production" && /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/.test(apiUrl ?? "")) {
    throw new Error(
      `VITE_API_URL=${apiUrl} is a local address; refusing to build a production bundle. ` +
      `Clear the override in web/.env.local before building.`
    );
  }

  return {
    plugins: [tailwindcss(), react()],
    resolve: {
      dedupe: ["react", "react-dom"],
    },
    // Component tests touch `window` (e.g. api.ts reads window.location.origin when
    // VITE_API_URL is unset, as in CI). Run under jsdom so the DOM globals exist.
    test: {
      environment: "jsdom",
      exclude: ["e2e/**", "node_modules/**", "dist/**", "src/fixtures/**"],
    },
    server: {
      port: 5174,
      // Dev-server only (rollup inlines the JSON regardless at build time):
      // web/src/host/contract.ts imports cli/src/yagent/sdk/contract.json,
      // outside Vite's default workspace-root fs.allow (web/package-lock.json
      // is the only lockfile, so the search stops at web/). Without this,
      // `GET /@fs/…/cli/…` 403s. See pages/review-2412-web-host-sdk.md.
      fs: {
        allow: [".."],
      },
      allowedHosts: ["488e-52-205-167-181.ngrok-free.app", "unreached-choppier-lakita.ngrok-free.dev", "y-agent.ngrok.app", "f9fb-52-205-167-181.ngrok-free.app", "971f-52-205-167-181.ngrok-free.app", "93bc-52-205-167-181.ngrok-free.app", "3121-52-205-167-181.ngrok-free.app", "7f86-52-205-167-181.ngrok-free.app", "da84-52-205-167-181.ngrok-free.app", "7155-52-205-167-181.ngrok-free.app", "df62-52-205-167-181.ngrok-free.app", "80c5-52-205-167-181.ngrok-free.app", "d0c4-52-205-167-181.ngrok-free.app", "591e-52-205-167-181.ngrok-free.app", "5c43-52-205-167-181.ngrok-free.app", "5462-52-205-167-181.ngrok-free.app", "luohy15.ngrok.app", "luohy15.ngrok.dev"],
      proxy: {
        "/api": "http://localhost:8001",
      },
    },
  };
});
