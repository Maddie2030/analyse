import { defineConfig } from '@playwright/test';

const resultsDir = process.env.MREADER_BROWSER_RESULTS_DIR || '/results/browser';

export default defineConfig({
  testDir: '.',
  timeout: 180_000,
  expect: { timeout: 20_000 },
  retries: 0,
  workers: 1,
  reporter: [
    ['line'],
    ['json', { outputFile: `${resultsDir}/playwright-reader.json` }],
  ],
  use: {
    baseURL: process.env.MREADER_BROWSER_BASE_URL || 'http://gateway',
    headless: true,
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  outputDir: `${resultsDir}/artifacts`,
});
