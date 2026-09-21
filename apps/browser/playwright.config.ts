// End-to-end: the built app, driven by Playwright, against the real API on the test
// database and a local site (ADR 0015). Run with `make test-browser-e2e`, which builds
// first and derives TEST_DATABASE_URL the way `make test-pg` does.

import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'test/e2e',
  testMatch: '*.spec.ts',
  globalSetup: './test/e2e/global-setup.ts',
  outputDir: 'test-results',
  workers: 1, // one API, one database: the tests share them
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [['list']],
  forbidOnly: !!process.env.CI,
});
