import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      // The dev server proxies /api, /t and /u so the browser only ever talks
      // to one origin. That keeps cookies, CORS and the tracking-pixel paths
      // behaving in development the way they do in production.
      proxy: Object.fromEntries(
        ['/api', '/t', '/u'].map((path) => [
          path,
          { target: env.DEV_API_TARGET || 'http://localhost:8000', changeOrigin: true },
        ]),
      ),
    },
    build: { outDir: 'dist', sourcemap: true },
  }
})
