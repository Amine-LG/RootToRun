import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import product from './product.json'

// The product name and descriptions come from product.json, the one place to change them (see src/lib/brand.ts).
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
const fields: Record<string, string> = { NAME: product.name, DESCRIPTION: product.description, SOCIAL: product.socialDescription }
const productHtml: Plugin = {
  name: 'product-metadata',
  transformIndexHtml: (html) => html.replace(/%PRODUCT_(NAME|DESCRIPTION|SOCIAL)%/g, (_, k: string) => esc(fields[k])),
}

export default defineConfig({
  plugins: [react(), productHtml],
  server: { host: '127.0.0.1', port: 5175, proxy: { '/api': 'http://127.0.0.1:8768', '/data': 'http://127.0.0.1:8768', '/media': 'http://127.0.0.1:8768' } },
  base: '/',
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 2000 },
})
