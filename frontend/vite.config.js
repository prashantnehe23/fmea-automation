import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/__tests__/setup.js',
    css: false,
  },
  server: {
    port: 5173,
    open: true,
    proxy: { '/api': 'http://localhost:8000' },
  },
});
