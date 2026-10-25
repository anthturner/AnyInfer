import {defineConfig} from '@playwright/test';

const channel = process.env.PLAYWRIGHT_CHANNEL as 'chrome' | 'msedge' | undefined;

export default defineConfig({
  testDir: './tests',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    screenshot: 'on',
    ...(channel ? {channel} : {}),
  },
  webServer: {
    command: 'node tests/static-server.mjs',
    url: 'http://127.0.0.1:4173/',
    reuseExistingServer: false,
  },
});
