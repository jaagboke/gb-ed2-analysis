import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Proxy /api to the local Flask server during development
    proxy: {
      '/api': 'http://localhost:5000',
    },
  },
})
