import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendPort = env.VITE_BACKEND_PORT || '8000'
  const frontendPort = parseInt(env.VITE_PORT || '5174')

  return {
    plugins: [react()],
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
