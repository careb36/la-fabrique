import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // Electron loads dist/index.html from file://, so it needs relative asset
  // URLs. The web build is served from the site root and must use absolute
  // ones: with './' a deep link such as /evidence/1 would request
  // /evidence/assets/... and render a blank page.
  // `npm run electron:build` selects it with `--mode electron` (an env var
  // prefix such as ELECTRON=1 does not work in Windows' cmd.exe); ELECTRON=1
  // is still honoured.
  base: process.env.ELECTRON || mode === 'electron' ? './' : '/',
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // The UI calls /v1 on its own origin; in docker compose the backend is
      // the `backend` service, not this container's localhost.
      '/v1': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
    watch: {
      usePolling: true,
      interval: 1000,
    },
  }
}))
