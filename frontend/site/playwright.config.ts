import { defineConfig, devices } from '@playwright/test';

// Runs against a production build; every API call is mocked in the tests.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:4317', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'],
    launchOptions: process.env.TRUSTLAYER_BROWSER_PATH ? { executablePath: process.env.TRUSTLAYER_BROWSER_PATH } : {},
  } }],
  webServer: {
    command: 'npm run build && npx vite preview --host 127.0.0.1 --port 4317 --strictPort',
    url: 'http://127.0.0.1:4317/',
    reuseExistingServer: false,
    timeout: 180000,
  },
});
