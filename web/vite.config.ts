import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";

// Dev-only: serve repo `docs/*.md` at `/docs-content/<slug>.md`,
// matching what `scripts/deploy-web.sh` produces in `web/dist/docs-content/`.
const docsContentMiddleware = () => ({
  name: "docs-content-middleware",
  configureServer(server: any) {
    server.middlewares.use((req: any, res: any, next: any) => {
      if (!req.url || !req.url.startsWith("/docs-content/")) return next();
      const rel = req.url.slice("/docs-content/".length).split("?")[0];
      if (!rel.endsWith(".md") || rel.includes("..") || rel.includes("/")) return next();
      const filePath = path.resolve(__dirname, "..", "docs", rel);
      if (!fs.existsSync(filePath)) return next();
      res.setHeader("Content-Type", "text/markdown; charset=utf-8");
      fs.createReadStream(filePath).pipe(res);
    });
  },
});

export default defineConfig({
  plugins: [tailwindcss(), react(), docsContentMiddleware()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  server: {
    port: 5174,
    allowedHosts: ["unreached-choppier-lakita.ngrok-free.dev", "y-agent.ngrok.app", "f9fb-52-205-167-181.ngrok-free.app", "971f-52-205-167-181.ngrok-free.app", "93bc-52-205-167-181.ngrok-free.app", "3121-52-205-167-181.ngrok-free.app", "7f86-52-205-167-181.ngrok-free.app", "da84-52-205-167-181.ngrok-free.app", "7155-52-205-167-181.ngrok-free.app", "df62-52-205-167-181.ngrok-free.app", "80c5-52-205-167-181.ngrok-free.app", "d0c4-52-205-167-181.ngrok-free.app", "591e-52-205-167-181.ngrok-free.app", "luohy15.ngrok.app", "luohy15.ngrok.dev"],
    proxy: {
      "/api": "http://localhost:8001",
    },
  },
});
