/**
 * Local history, end to end (ADR 0016): the History menu, recently closed tabs, and the
 * history page, checked where they land -- in the menu, the tab strip and the page.
 */

import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

import type { Page } from '@playwright/test';

import { BrowserApp, OTHER_SITE, SITE, expect, expectFocused, test } from './fixtures';

const DAY = 24 * 60 * 60 * 1000;

/** The rows of the history page, as their titles. */
const rows = (page: Page) => page.locator('.row .title');

function localDay(at: number): string {
  const date = new Date(at);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

test('the History menu lists the pages visited, with their favicons, and opens them', async ({ smart }) => {
  await smart.go(SITE('/article.html'));
  await smart.go(SITE('/second.html'));
  await smart.go(SITE('/article.html#section')); // a fragment is the same page, not a visit

  await expect.poll(() => smart.menuItem('recent-0')).toMatchObject({ label: 'Tuning Postgres', icon: true });
  expect(await smart.menuItem('recent-1')).toMatchObject({ label: 'Second page', toolTip: SITE('/second.html') });
  expect(await smart.menuItem('recent-2')).toBeNull();

  await smart.menu('recent-1');
  await expect(smart.chrome().locator('.omnibox')).toHaveValue(SITE('/second.html'));
  expect(await smart.accelerator('show-history')).toBe(process.platform === 'darwin' ? 'Cmd+Y' : 'Ctrl+H');
  expect(await smart.accelerator('search-history')).toBe('Alt+CmdOrCtrl+Y');
  expect(await smart.accelerator('delete-browsing-data')).toBe('CmdOrCtrl+Shift+Backspace');
});

test('a closed tab reopens where it was, with its back history', async ({ smart }) => {
  await smart.go(SITE('/article.html'));
  await smart.menu('new-tab');
  await smart.go(SITE('/links.html'));
  await smart.go(SITE('/second.html'));
  await smart.menu('new-tab');
  await smart.go(SITE('/untitled.html'));
  const titles = smart.chrome().locator('.tab .title');
  const untitled = SITE('/untitled.html').replace(/^http:\/\//, '');

  expect(await smart.menuItem('reopen-closed-tab')).toMatchObject({ enabled: false });
  await smart.menu('tab-2');
  await smart.menu('close-tab');
  await expect(titles).toHaveText(['Tuning Postgres', untitled]);

  expect(await smart.accelerator('reopen-closed-tab')).toBe('CmdOrCtrl+Shift+T');
  await expect.poll(() => smart.menuItem('closed-0')).toMatchObject({ label: 'Second page', icon: true });
  await smart.menu('reopen-closed-tab');
  await expect(titles).toHaveText(['Tuning Postgres', 'Second page', untitled]);
  await expect(smart.chrome().locator('.tab.active .title')).toHaveText('Second page');

  const back = smart.chrome().getByRole('button', { name: 'Back' });
  await expect(back).toBeEnabled();
  await back.click();
  await expect(smart.chrome().locator('.omnibox')).toHaveValue(SITE('/links.html'));

  // And from the Recently Closed submenu, by name.
  await smart.menu('close-tab');
  await expect(titles).toHaveText(['Tuning Postgres', untitled]);
  await expect.poll(() => smart.menuItem('closed-0')).toMatchObject({ label: 'Links' });
  await smart.menu('closed-0');
  await expect(titles).toHaveText(['Tuning Postgres', 'Links', untitled]);
  await expect.poll(() => smart.menuItem('reopen-closed-tab')).toMatchObject({ enabled: false });
});

test('the history page lists visits by day, searches them, and narrows to a site', async ({ smart }) => {
  await smart.go(SITE('/article.html'));
  await smart.go(SITE('/untitled.html'));
  await smart.go(OTHER_SITE('/second.html'));

  await smart.menu('show-history');
  const page = await smart.historyPage();
  await expect(smart.chrome().locator('.tab.active .title')).toHaveText('History');
  await expect(smart.chrome().locator('.tab.active .favicon img')).toHaveAttribute('src', /^data:image\/svg\+xml;base64,/);
  await expect(page.getByRole('heading', { level: 2 })).toHaveText(/^Today - /);
  await expect(rows(page)).toHaveText(['Second page', SITE('/untitled.html'), 'Tuning Postgres']);
  await expect(page.locator('.row .host')).toHaveText(['localhost', '127.0.0.1', '127.0.0.1']);
  await expect(page.locator('.row .favicon img')).toHaveCount(3);
  await expectFocused(page.getByLabel('Search history')); // ready to type, as Chrome's is
  await smart.snapshot('10-history');

  // Search: words starting words of the title or address.
  await page.getByLabel('Search history').fill('tun');
  await expect(rows(page)).toHaveText(['Tuning Postgres']);
  await page.getByLabel('Search history').fill('nothing-like-this');
  await expect(page.getByText('No history matches')).toBeVisible();
  await page.getByLabel('Search history').press('Escape');
  await expect(rows(page)).toHaveCount(3);

  // More from this site.
  await page.getByRole('button', { name: 'Actions for Tuning Postgres' }).click();
  await smart.snapshot('11-history-menu');
  await page.getByRole('menuitem', { name: 'More from this site' }).click();
  await expect(rows(page)).toHaveText([SITE('/untitled.html'), 'Tuning Postgres']);
  await expect(page.locator('.filter')).toHaveText('127.0.0.1');
  await expect(smart.chrome().locator('.omnibox')).toHaveValue('smart://history/?host=127.0.0.1');
  await page.getByRole('button', { name: 'Show all sites' }).click();
  await expect(rows(page)).toHaveCount(3);

  // History for This Site, from the menu, for the page a tab shows.
  await smart.menu('tab-1');
  await smart.menu('new-tab');
  await smart.go(OTHER_SITE('/links.html'));
  await smart.menu('site-history');
  await expect(rows(await smart.historyPage())).toHaveText(['Links', 'Second page']);
  await expect(smart.chrome().locator('.tab')).toHaveCount(3); // the page already open, reused
});

test('a page opened from history opens in its tab, and Back returns to history', async ({ smart }) => {
  await smart.go(SITE('/article.html'));
  await smart.go(SITE('/second.html'));
  await smart.menu('new-tab');
  await smart.menu('show-history'); // a blank tab becomes the history page
  await expect(smart.chrome().locator('.tab')).toHaveCount(1 + 1);
  const page = await smart.historyPage();

  // ⌘-click: a new tab behind this one.
  await rows(page).filter({ hasText: 'Second page' }).click({ modifiers: ['ControlOrMeta'] });
  await expect(smart.chrome().locator('.tab .title')).toHaveText(['Second page', 'History', 'Second page']);
  await expect(smart.chrome().locator('.tab.active .title')).toHaveText('History');

  await rows(page).filter({ hasText: 'Tuning Postgres' }).click();
  await expect(smart.chrome().locator('.omnibox')).toHaveValue(SITE('/article.html'));
  await expect(smart.chrome().locator('.tab.active .title')).toHaveText('Tuning Postgres');
  await expect((await smart.tab(SITE('/article.html'))).locator('h1')).toHaveText('Tuning Postgres');

  await smart.menu('back');
  await expect(smart.chrome().locator('.omnibox')).toHaveValue('smart://history/');
  await expect(rows(await smart.historyPage())).toHaveCount(2);
});

test('deleting from history: a row, ticked rows, and browsing data', async ({ smart }) => {
  await smart.go(SITE('/article.html'));
  await smart.go(SITE('/second.html'));
  const tab = await smart.go(SITE('/links.html'));
  await tab.evaluate(() => (document.cookie = 'visited=yes; max-age=3600; path=/'));
  await smart.menu('new-tab');
  await smart.menu('show-history');
  const page = await smart.historyPage();
  await expect(rows(page)).toHaveText(['Links', 'Second page', 'Tuning Postgres']);

  // One row, from its menu: gone from the page and from the History menu.
  await page.getByRole('button', { name: 'Actions for Links' }).click();
  await page.getByRole('menuitem', { name: 'Delete from history' }).click();
  await expect(rows(page)).toHaveText(['Second page', 'Tuning Postgres']);
  await expect.poll(async () => (await smart.menuItem('recent-0'))?.label).toBe('Second page');

  // Ticked rows, confirmed.
  await page.getByLabel('Select Second page').check();
  await page.getByLabel('Select Tuning Postgres').check();
  await expect(page.locator('header')).toContainText('2 selected');
  await smart.snapshot('12-history-selected');
  await page.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('These 2 pages will be deleted');
  await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByText('Pages you visit appear here')).toBeVisible();
  await expect.poll(() => smart.menuItem('recent-0')).toBeNull();

  // Delete browsing data, from the menu: cookies too.
  await smart.menu('tab-1');
  await smart.go(SITE('/article.html'));
  expect(await (await smart.tab(SITE('/article.html'))).evaluate(() => document.cookie)).toBe('visited=yes');
  await smart.menu('delete-browsing-data');
  const again = await smart.historyPage();
  const dialog = again.getByRole('dialog');
  await expect(dialog).toContainText('Delete browsing data');
  await dialog.getByLabel('Time range').selectOption('all');
  await dialog.getByRole('checkbox', { name: /Cookies and other site data/ }).check();
  await smart.snapshot('13-delete-browsing-data');
  await dialog.getByRole('button', { name: 'Delete data' }).click();
  await expect(dialog).toBeHidden();
  await expect(again.getByText('Pages you visit appear here')).toBeVisible();

  await smart.menu('tab-1');
  expect(await (await smart.go(SITE('/second.html'))).evaluate(() => document.cookie)).toBe('');
});

test('the history page comes back on the next launch, showing what it showed', async () => {
  const first = await BrowserApp.launch();
  await first.go(SITE('/article.html'));
  await first.go(SITE('/second.html'));
  await first.menu('search-history');
  const page = await first.historyPage();
  await expectFocused(page.getByLabel('Search history'));
  await page.getByLabel('Search history').fill('second');
  await expect(rows(page)).toHaveText(['Second page']);
  await expect(first.chrome().locator('.omnibox')).toHaveValue('smart://history/?q=second');
  await first.close();

  const second = await BrowserApp.launch(first.profile);
  try {
    const restored = await second.historyPage();
    await expect(restored.getByLabel('Search history')).toHaveValue('second');
    await expect(rows(restored)).toHaveText(['Second page']);
  } finally {
    await second.dispose();
  }
});

test('earlier days each get a submenu, and history older than 90 days is forgotten', async () => {
  const first = await BrowserApp.launch();
  await first.close();
  // Visits from other days, written as the browser would have written them.
  const db = new DatabaseSync(join(first.profile, 'history.db'));
  const visit = (url: string, title: string, at: number) => {
    const { id } = db
      .prepare('INSERT INTO page (url, host, title) VALUES (?, ?, ?) RETURNING id')
      .get(url, new URL(url).hostname, title) as { id: number };
    db.prepare('INSERT INTO visit (page_id, at, day) VALUES (?, ?, ?)').run(id, at, localDay(at));
  };
  const now = Date.now();
  visit(SITE('/second.html'), 'Second page', now - DAY);
  visit(SITE('/links.html'), 'Links', now - 3 * DAY);
  visit(SITE('/article.html'), 'Tuning Postgres', now - 100 * DAY);
  db.close();

  const smart = await BrowserApp.launch(first.profile);
  try {
    expect(await smart.menuItem('day-0')).toMatchObject({ label: 'Yesterday' });
    expect(await smart.menuItem('day-0-page-0')).toMatchObject({ label: 'Second page' });
    expect(await smart.menuItem('day-1-page-0')).toMatchObject({ label: 'Links' });
    expect(await smart.menuItem('day-2')).toBeNull(); // 100 days ago: pruned at launch

    await smart.menu('day-1-all');
    const page = await smart.historyPage();
    await expect(rows(page)).toHaveText(['Links']);
    await expect(page.locator('.filter')).toHaveCount(1);
    await page.getByRole('button', { name: 'Show all days' }).click();
    await expect(rows(page)).toHaveText(['Second page', 'Links']);
  } finally {
    await smart.dispose();
  }
});

test('the history page cannot be reached from a web page, and reaches only history', async ({ smart }) => {
  const web = await smart.go(SITE('/article.html'));
  await web.evaluate(() => {
    location.href = 'smart://history/';
  });
  await web.waitForTimeout(300);
  await expect(smart.chrome().locator('.omnibox')).toHaveValue(SITE('/article.html'));

  await smart.menu('show-history');
  const page = await smart.historyPage();
  const bridge = await page.evaluate(() => Object.keys((window as unknown as { smart: object }).smart).sort());
  expect(bridge).toEqual(['clear', 'onChanged', 'onView', 'open', 'query', 'remove']);
  expect(await page.evaluate(() => typeof (globalThis as unknown as { require?: unknown }).require)).toBe('undefined');
  // It opens web pages and nothing else.
  await page.evaluate(() => (window as unknown as { smart: { open(u: string, h: string): Promise<void> } }).smart.open('javascript:alert(1)', 'current'));
  await expect(smart.chrome().locator('.omnibox')).toHaveValue('smart://history/');
});
