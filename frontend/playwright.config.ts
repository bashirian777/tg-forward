import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  use: { baseURL: 'http://127.0.0.1:18082', launchOptions: { executablePath: process.env.CHROMIUM_PATH }, trace: 'retain-on-failure' },
  webServer: { command: `${process.env.UI_PYTHON || '../.venv/bin/python'} ../tests/web/serve.py`, url: 'http://127.0.0.1:18082', reuseExistingServer: false, timeout: 15000 },
})
