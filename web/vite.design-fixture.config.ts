import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";

/**
 * Host consumption check for @y/design (todo 3657). Not the app build.
 * Uses the same Tailwind/React plugins, with the fixture as the only entry.
 */
export default defineConfig({
  plugins: [tailwindcss(), react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  build: {
    outDir: "dist-design-fixture",
    emptyOutDir: true,
    rollupOptions: {
      input: "src/fixtures/design-table-check.tsx",
    },
  },
});
