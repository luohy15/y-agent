import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [tailwindcss(), react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  server: {
    port: 5174,
    allowedHosts: ["unreached-choppier-lakita.ngrok-free.dev", "f9fb-52-205-167-181.ngrok-free.app", "971f-52-205-167-181.ngrok-free.app", "93bc-52-205-167-181.ngrok-free.app"],
    proxy: {
      "/api": "http://localhost:8001",
    },
  },
});
