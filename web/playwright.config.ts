import { defineConfig } from '@playwright/test';

/** 验收连接已启动的真实本地服务；默认不记录可能包含客户内容的截图或轨迹。 */
export default defineConfig({
  testDir: './tests',
  timeout: 60000,
  expect: { timeout: 15000 },
  workers: 1,
  retries: 0,
  reporter: 'list',
  outputDir: '../data/browser-tests',
  use: {
    baseURL: process.env.DAKE_WEB_URL || 'http://127.0.0.1:8000',
    browserName: 'chromium',
    viewport: { width: 1440, height: 1000 },
    launchOptions: process.env.DAKE_BROWSER_PATH
      ? { executablePath: process.env.DAKE_BROWSER_PATH }
      : {},
    actionTimeout: 10000,
    screenshot: 'off',
    trace: 'off',
    video: 'off',
  },
});
