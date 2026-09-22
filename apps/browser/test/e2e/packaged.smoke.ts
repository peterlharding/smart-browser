/**
 * The packaged app starts and quits (ADR 0018), for CI's macOS runner, which has no
 * Postgres for the API: the full suite runs against the package locally, with
 * `make test-browser-e2e-packaged`. This proves what only packaging can break: the UI and
 * the preloads served from inside app.asar, the history page's own address, the profile
 * the app chooses, and quitting cleanly.
 */

import { BrowserApp, PACKAGED_APP, expect, test } from './fixtures';

test('the packaged app shows its own pages from inside its archive, and quits', async () => {
  expect(PACKAGED_APP(), 'SMART_BROWSER_APP names the app under test').toBeTruthy();
  const smart = await BrowserApp.launch();
  try {
    expect(await smart.app.evaluate(({ app }) => app.isPackaged)).toBe(true);
    expect(await smart.app.evaluate(({ app }) => app.getName())).toBe('Smart-Browser');
    await expect(smart.chrome().locator('.tab .title')).toHaveText('New Tab');

    await smart.menu('show-history');
    const history = await smart.historyPage();
    await expect(history.getByRole('heading', { name: 'History', level: 1 })).toBeVisible();
    await expect(history.getByText('Pages you visit appear here')).toBeVisible();

    await smart.menu('settings');
    await expect((await smart.overlay()).getByRole('heading', { name: 'Settings' })).toBeVisible();
    await smart.snapshot('30-packaged');
  } finally {
    await smart.dispose(); // fails if the app does not quit
  }
});
