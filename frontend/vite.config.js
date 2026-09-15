import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In local dev (`npm run dev`), proxy /api to a backend running on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
