import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendPort = env.VITE_BACKEND_PORT || '8000'
  const frontendPort = parseInt(env.VITE_PORT || '5174')

  return {
    plugins: [
      react(),
      VitePWA({
        registerType: 'autoUpdate',
        strategies: 'injectManifest',
        srcDir: 'src',
        filename: 'sw.ts',
        includeAssets: ['icon-192.png', 'icon-512.png', 'apple-touch-icon.png'],
        manifest: {
          name: 'Sistema Café',
          short_name: 'Café',
          description: 'Sistema operativo para cafeterías',
          theme_color: '#2d1810',
          background_color: '#2d1810',
          display: 'standalone',
          orientation: 'portrait',
          start_url: '/',
          scope: '/',
          icons: [
            { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
            { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
          ],
        },
        // En injectManifest el precache lo arma el SW custom (src/sw.ts). El
        // runtimeCaching de workbox.* NO aplica en esta estrategia.
        injectManifest: {
          globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        },
      }),
    ],
    server: {
      host: '0.0.0.0',
      port: frontendPort,
      proxy: {
        '/api': `http://127.0.0.1:${backendPort}`,
        '/uploads': `http://127.0.0.1:${backendPort}`,
      },
    },
    preview: {
      host: '0.0.0.0',
      port: frontendPort,
    },
  }
})
