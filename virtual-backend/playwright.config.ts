import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: {
    timeout: 8_000,
  },
  use: {
    baseURL: 'http://127.0.0.1:5174',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5174 --strictPort',
    cwd: '../frontend',
    env: {
      VITE_BT_PROXY_TARGET: 'http://127.0.0.1:18080',
      VITE_SY_PROXY_TARGET: 'http://127.0.0.1:18081',
      VITE_BT_BACKEND_PORT: '18080',
      VITE_SY_BACKEND_PORT: '18081',
      VITE_BT_WS_PORT: '18080',
      VITE_SY_WS_PORT: '18081',
    },
    url: 'http://127.0.0.1:5174/login',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
