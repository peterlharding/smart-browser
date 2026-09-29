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

    // Updates are off under test, so the app asked the service nothing: with no feed set,
    // it does not know where it would ask (ADR 0019).
    expect(await smart.app.evaluate(({ autoUpdater }) => autoUpdater.getFeedURL())).toBe('');
    expect(await smart.menuItem('check-for-updates')).toMatchObject({ enabled: false });
    expect(await smart.menuItem('restart-to-update')).toBeNull();

    await smart.menu('settings');
    const settings = await smart.overlay();
    await expect(settings.getByRole('heading', { name: 'Settings' })).toBeVisible();
    // A packaged app offers the switch, on by default, and still asks the service nothing.
    await expect(settings.getByLabel('Check for updates automatically')).toBeChecked();
    await settings.getByLabel('Check for updates automatically').uncheck();
    await settings.getByRole('button', { name: 'Save' }).click();
    await expect.poll(() => smart.overlayOpen()).toBe(false);
    expect(await smart.app.evaluate(({ autoUpdater }) => autoUpdater.getFeedURL())).toBe('');
    await smart.menu('settings');
    await smart.snapshot('30-packaged-settings');
  } finally {
    await smart.dispose(); // fails if the app does not quit
  }
});
