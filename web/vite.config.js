import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The build lands inside the Python package so `spidey serve` ships it and
// `pip install` users never need Node.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../spidey/server/static',
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` proxies the socket to a locally running `spidey serve`.
    proxy: {
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
