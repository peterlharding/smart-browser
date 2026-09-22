// The packaged app's smoke test (ADR 0018): no API, no database, no local site, so it
// runs on CI's macOS runner. `make browser-package-check` packages the app and runs it.

import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'test/e2e',
  testMatch: 'packaged.smoke.ts',
  outputDir: 'test-results',
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list']],
  forbidOnly: !!process.env.CI,
});
