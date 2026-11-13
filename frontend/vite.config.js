import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The API runs on :8000. In dev and preview, /api/* is proxied there so the
// app and API share an origin (no CORS, and the service worker can cache it).
const proxy = {
  '/api': { target: process.env.API_TARGET ?? 'http://localhost:8000', changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: Number(process.env.PORT) || 5173, strictPort: !!process.env.PORT, host: true, proxy },
  preview: { port: 4173, host: true, proxy },
})
