import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:8765', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'],
    launchOptions: process.env.TRUSTLAYER_BROWSER_PATH ? { executablePath: process.env.TRUSTLAYER_BROWSER_PATH } : {},
  } }],
  webServer: {
    command: process.platform === 'win32'
      ? '..\\..\\.venv\\Scripts\\python.exe ..\\..\\tests\\browser_server.py'
      : '../../.venv/bin/python ../../tests/browser_server.py',
    url: 'http://127.0.0.1:8765/workbench/',
    reuseExistingServer: false,
    timeout: 30000,
  },
});
