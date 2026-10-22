import { fileURLToPath } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const page = (path: string) => fileURLToPath(new URL(path, import.meta.url));
const api = { '/v1': 'http://127.0.0.1:8000' };

export default defineConfig({
  plugins: [react(), tailwindcss(), {
    // Social sites need an absolute image URL: build with SITE_URL=https://your-domain.
    name: 'absolute-og-image',
    apply: 'build',
    buildStart() {
      if (!process.env.SITE_URL) this.warn('SITE_URL is not set: link previews (LinkedIn, X, WhatsApp) will have no image.');
    },
    transformIndexHtml: html => html.replaceAll('content="/og.jpg"', `content="${(process.env.SITE_URL ?? '').replace(/\/+$/, '')}/og.jpg"`),
  }],
  build: {
    chunkSizeWarningLimit: 600, // three.js (~530 kB) is its own chunk, loaded after first paint
    rolldownOptions: {
      input: {
        home: page('./index.html'),
        check: page('./check/index.html'),
        demo: page('./demo/index.html'),
        report: page('./report/sample/index.html'),
      },
    },
  },
  server: { proxy: api },
  preview: { proxy: api },
  test: { include: ['src/**/*.test.ts'], environment: 'node' },
});
