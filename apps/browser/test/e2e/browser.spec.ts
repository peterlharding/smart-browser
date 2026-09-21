/**
 * The first slice, end to end (ADR 0015): the built app against the real API and a local
 * site. Each test is a thing a person does, checked where it lands -- in the chrome, in the
 * page, and in the API.
 */

import type { Bookmark } from '../../src/shared/ipc';
import { API, BrowserApp, SITE, TOKEN, expect, expectFocused, test } from './fixtures';

async function lookup(url: string): Promise<Bookmark> {
  const response = await fetch(`${API()}/api/v1/bookmarks/lookup?url=${encodeURIComponent(url)}`, {
    headers: { Authorization: `Bearer ${TOKEN()}` },
  });
  if (!response.ok) throw new Error(`lookup ${url}: ${response.status}`);
  return (await response.json()) as Bookmark;
}

test('a new window opens one blank tab, with the omnibox ready to type', async ({ smart }) => {
  const chrome = smart.chrome();
  await expect(chrome.locator('.tab')).toHaveCount(1);
  await expect(chrome.locator('.tab .title')).toHaveText('New Tab');
  await expectFocused(chrome.locator('.omnibox'));
  await expect(chrome.locator('.save')).toBeDisabled(); // a blank page cannot be saved
  await smart.snapshot('01-new-window');
});

test('typing an address loads the page, with its title and favicon', async ({ smart }) => {
  await smart.go(SITE('/article.html'));
  const chrome = smart.chrome();
  await expect(chrome.locator('.tab .title')).toHaveText('Tuning Postgres');
  await expect(chrome.locator('.tab .favicon img')).toHaveAttribute('src', /^data:image\/svg\+xml;base64,/);
  await expect(chrome.locator('.omnibox')).toHaveValue(SITE('/article.html'));
  await expect((await smart.tab(SITE('/article.html'))).locator('h1')).toHaveText('Tuning Postgres');
});

test('a page with no title is named by its host and path, as Chrome names it', async ({ smart }) => {
  await smart.go(SITE('/untitled.html'));
  await expect(smart.chrome().locator('.tab .title')).toHaveText(SITE('/untitled.html').replace(/^http:\/\//, ''));
});

test('an unconfigured browser sends the save button to settings', async ({ smart }) => {
  await smart.go(SITE('/article.html'));
  const save = smart.chrome().locator('.save');
  await expect(save).toHaveAttribute('title', 'Connect to your bookmarks API in Settings');
  await save.click();
  await expect((await smart.overlay()).getByRole('heading', { name: 'Settings' })).toBeVisible();
});

test('settings test the connection, then keep the token', async ({ smart }) => {
  await smart.menu('settings');
  const overlay = await smart.overlay();
  await expectFocused(overlay.getByLabel('Bookmarks API')); // ready to type on open
  await overlay.getByLabel('Bookmarks API').fill(API());
  await overlay.getByLabel('API token').fill('wrong-token');
  await overlay.getByRole('button', { name: 'Test connection' }).click();
  await expect(overlay.getByRole('status')).toHaveText('Token rejected. Check Settings.');

  await overlay.getByLabel('API token').fill(TOKEN());
  await overlay.getByRole('button', { name: 'Test connection' }).click();
  await expect(overlay.getByRole('status')).toContainText(/Connected: API [\d.]+, contract 1, schema 0003\./);
  // One thing looks focused at a time: the card, not the omnibox behind it.
  await expectFocused(smart.chrome().locator('.omnibox'), false);
  await smart.snapshot('02-settings');
  await overlay.getByRole('button', { name: 'Save' }).click();
  await expect.poll(() => smart.overlayOpen()).toBe(false);

  // Reopened, the token is not shown again, only said to be stored.
  await smart.menu('settings');
  const reopened = await smart.overlay();
  await expect(reopened.getByLabel('API token')).toHaveValue('');
  await expect(reopened.getByLabel('API token')).toHaveAttribute('placeholder', /Stored in the Keychain/);
});

test('the save sheet saves the page with its tags and the title seen', async ({ smart }) => {
  await smart.configure();
  const url = SITE('/article.html');
  await smart.go(url);
  const save = smart.chrome().locator('.save');
  await expect(save).toHaveAttribute('title', 'Save this page with tags (⌘⇧B)');

  expect(await smart.accelerator('save-sheet')).toBe('CmdOrCtrl+Shift+B');
  await smart.menu('save-sheet');
  const overlay = await smart.overlay();
  await expect(overlay.getByText('Not saved yet')).toBeVisible();
  await expect(overlay.getByRole('heading', { name: 'Tuning Postgres' })).toBeVisible();
  await overlay.getByLabel('Tags', { exact: true }).fill('postgres performance');
  await smart.snapshot('03-save-sheet');
  await overlay.getByLabel('Tags', { exact: true }).press('Enter');

  await expect.poll(() => smart.overlayOpen()).toBe(false);
  await expect(save).toHaveAttribute('title', 'Saved with performance, postgres (⌘⇧B)');
  await expect(save.locator('.count')).toHaveText('2');
  const saved = await lookup(url);
  expect(saved.tags).toEqual(['performance', 'postgres']);
  expect(saved.title).toBe('Tuning Postgres'); // the title seen, ADR 0010
  expect(saved.saved_from).toBe('smart-browser');
  await smart.snapshot('04-saved');
});

test('the save sheet shows existing tags, suggests from your vocabulary, and removes', async ({ smart }) => {
  await smart.configure();
  const url = SITE('/second.html');
  await smart.go(url);
  await smart.menu('save-sheet');
  const overlay = await smart.overlay();
  await overlay.getByLabel('Tags', { exact: true }).fill('postgres reading');
  await overlay.getByLabel('Tags', { exact: true }).press('Enter');
  await expect.poll(() => smart.overlayOpen()).toBe(false);

  await smart.menu('save-sheet');
  const again = await smart.overlay();
  await expect(again.getByText('Saved', { exact: true })).toBeVisible();
  const current = again.getByRole('list', { name: 'Tags on this page' });
  await expect(current.getByRole('button')).toHaveText(['postgres', 'reading']);

  // Suggestions come from your own tags, ranked by use, and Tab takes the first.
  await again.getByLabel('Tags', { exact: true }).fill('perf');
  await expect(again.getByRole('list', { name: 'Suggestions' }).getByRole('button').first()).toContainText(
    'performance',
  );
  await again.getByLabel('Tags', { exact: true }).press('Tab');
  await expect(again.getByLabel('Tags', { exact: true })).toHaveValue('performance, ');

  await current.getByRole('button', { name: 'reading' }).click();
  await expect(current.getByRole('button')).toHaveText(['postgres']);
  expect((await lookup(url)).tags).toEqual(['postgres']);
});

test('quick save keeps the page without asking for tags', async ({ smart }) => {
  await smart.configure();
  const url = SITE('/links.html');
  await smart.go(url);
  expect(await smart.accelerator('quick-save')).toBe('CmdOrCtrl+Shift+S');
  await smart.menu('quick-save');
  await expect(smart.chrome().locator('.save')).toHaveAttribute('title', 'Saved, untagged (⌘⇧B)');
  expect((await lookup(url)).tags).toEqual([]);
});

test('a page is looked up once, not on every step of its loading', async ({ smart }) => {
  await smart.configure();
  const lookups = await smart.countLookups();
  await smart.go(SITE('/stages.html'));
  const save = smart.chrome().locator('.save');
  await expect(save).toHaveAttribute('title', 'Save this page with tags (⌘⇧B)');
  await (await smart.tab(SITE('/stages.html'))).waitForTimeout(300); // let the stages finish
  expect(await lookups()).toBe(1);

  // Switching away and back asks nothing new: the answer is a second old.
  await smart.menu('new-tab');
  await smart.menu('tab-1');
  await expect(save).toHaveAttribute('title', 'Save this page with tags (⌘⇧B)');
  expect(await lookups()).toBe(1);

  // Reloading is asking again.
  await smart.menu('reload');
  await expect.poll(lookups).toBe(2);
});

test('a link that opens a window opens a tab beside its page instead', async ({ smart }) => {
  await smart.go(SITE('/links.html'));
  await smart.menu('new-tab');
  await smart.menu('tab-1');
  await (await smart.tab(SITE('/links.html'))).locator('#blank').click();

  const titles = smart.chrome().locator('.tab .title');
  await expect(titles).toHaveText(['Links', 'Second page', 'New Tab']);
  await expect(smart.chrome().locator('.tab.active .title')).toHaveText('Second page');
  // A tab opened from a link goes to its page; only a new blank tab wants the omnibox.
  await expectFocused(smart.chrome().locator('.omnibox'), false);
  await expect(smart.chrome().locator('.omnibox')).toHaveValue(SITE('/second.html'));
  await smart.snapshot('05-tabs');
});

test('tabs open, switch and close from the keyboard', async ({ smart }) => {
  await smart.go(SITE('/article.html'));
  expect(await smart.accelerator('new-tab')).toBe('CmdOrCtrl+T');
  await smart.menu('new-tab');
  await expectFocused(smart.chrome().locator('.omnibox'));
  await smart.go(SITE('/second.html'));

  const active = smart.chrome().locator('.tab.active .title');
  await smart.menu('tab-1');
  await expect(active).toHaveText('Tuning Postgres');
  await smart.menu('tab-9');
  await expect(active).toHaveText('Second page');
  await smart.menu('next-tab');
  await expect(active).toHaveText('Tuning Postgres');

  await smart.menu('close-tab');
  await expect(smart.chrome().locator('.tab .title')).toHaveText(['Second page']);
});

test('a tab dragged along the strip moves there, and stays there', async ({ smart }) => {
  await smart.go(SITE('/article.html'));
  await smart.menu('new-tab');
  await smart.go(SITE('/second.html'));
  const titles = smart.chrome().locator('.tab .title');
  await expect(titles).toHaveText(['Tuning Postgres', 'Second page']);

  await smart.chrome().locator('.tab', { hasText: 'Second page' }).dragTo(smart.chrome().locator('.tab').first());
  await expect(titles).toHaveText(['Second page', 'Tuning Postgres']);
  await smart.menu('tab-1'); // ⌘1 is the first tab by position, so the order is real
  await expect(smart.chrome().locator('.tab.active .title')).toHaveText('Second page');
});

test('back and forward follow the tab’s history', async ({ smart }) => {
  await smart.go(SITE('/article.html'));
  await smart.go(SITE('/second.html'));
  const chrome = smart.chrome();
  await expect(chrome.getByRole('button', { name: 'Forward' })).toBeDisabled();

  await smart.menu('back');
  await expect(chrome.locator('.omnibox')).toHaveValue(SITE('/article.html'));
  await expect(chrome.getByRole('button', { name: 'Forward' })).toBeEnabled();
  await chrome.getByRole('button', { name: 'Forward' }).click();
  await expect(chrome.locator('.omnibox')).toHaveValue(SITE('/second.html'));
});

test('the next launch reopens the tabs that were open', async () => {
  const first = await BrowserApp.launch();
  await first.go(SITE('/article.html'));
  await first.menu('new-tab');
  await first.go(SITE('/second.html'));
  await first.menu('tab-1');
  await expect(first.chrome().locator('.tab.active .title')).toHaveText('Tuning Postgres');
  await first.close();

  const second = await BrowserApp.launch(first.profile);
  await expect(second.chrome().locator('.tab .title')).toHaveText(['Tuning Postgres', 'Second page']);
  await expect(second.chrome().locator('.tab.active .title')).toHaveText('Tuning Postgres');
  await second.dispose(); // the same profile as first's, so this removes both
});

test('pages cannot reach the browser, and asking for a permission is refused', async ({ smart }) => {
  const page = await smart.go(SITE('/article.html'));
  expect(await page.evaluate(() => typeof (window as unknown as { smart?: unknown }).smart)).toBe('undefined');
  expect(await page.evaluate(() => typeof (globalThis as unknown as { require?: unknown }).require)).toBe('undefined');
  const permission = await page.evaluate(async () => (await navigator.permissions.query({ name: 'geolocation' })).state);
  expect(permission).toBe('denied');
  // smart:// is registered for the browser's own UI only; a page cannot load it.
  const loaded = await page.evaluate(() => fetch('smart://ui/chrome.html').then(() => true, () => false));
  expect(loaded).toBe(false);
});
