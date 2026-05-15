import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Renderer is loaded via file:// from the main process, so base must be relative.
export default defineConfig({
  root: 'src/renderer',
  base: './',
  plugins: [react()],
  build: {
    outDir: '../../dist/renderer',
    emptyOutDir: true,
  },
});
