import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Microclimate Studio — Vite config
// Tailwind v4 is wired through the official Vite plugin (no tailwind.config needed).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Dev proxy to the FastAPI backend so the app can use relative /api paths if needed.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    sourcemap: false,
    target: 'es2022',
  },
});
