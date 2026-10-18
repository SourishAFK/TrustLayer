import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/workbench/',
  plugins: [react()],
  server: {
    proxy: { '/v1': 'http://127.0.0.1:8000', '/docs': 'http://127.0.0.1:8000' },
  },
  test: { include: ['src/**/*.test.ts'], environment: 'node' },
});
