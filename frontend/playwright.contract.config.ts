import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/contract',
  outputDir: './test-results/contract',
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:18083', launchOptions: { executablePath: process.env.CHROMIUM_PATH }, trace: 'retain-on-failure' },
  webServer: {
    command: `cd .. && ${process.env.UI_PYTHON || '.venv/bin/python'} -m tests.web.contract_server`,
    url: 'http://127.0.0.1:18083', reuseExistingServer: false, timeout: 15000,
  },
})
