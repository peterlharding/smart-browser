/**
 * The offline save queue, end to end (ADR 0017): the browser against the real API through
 * a proxy the test can take away, as `make api-dev` not running would. Each save is checked
 * where it lands: on the save button, in the menu, and in the API.
 */

import type { Bookmark } from '../../src/shared/ipc';
import { API, BrowserApp, SITE, TOKEN, expect, recordApi, type ApiRecorder } from './fixtures';
import { test as base } from '@playwright/test';

/** The API's own answer for *url*, asked directly: null when it has no save of it. */
async function lookup(url: string): Promise<Bookmark | null> {
  const response = await fetch(`${API()}/api/v1/bookmarks/lookup?url=${encodeURIComponent(url)}`, {
    headers: { Authorization: `Bearer ${TOKEN()}` },
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`lookup ${url}: ${response.status}`);
  return (await response.json()) as Bookmark;
}

const tagsOf = async (url: string) => (await lookup(url))?.tags ?? null;

// A browser configured against a proxy in front of the API, which each test can take away.
const test = base.extend<{ api: ApiRecorder; smart: BrowserApp }>({
  // eslint-disable-next-line no-empty-pattern
  api: async ({}, use) => {
    const api = await recordApi();
    await use(api);
    await api.close();
  },
  smart: async ({ api }, use) => {
    const smart = await BrowserApp.launch();
    await smart.configure(api.url);
    await use(smart);
    await smart.dispose();
  },
});

test('a quick save while the API is away waits, and goes when you retry', async ({ api, smart }) => {
  const url = SITE('/article.html?queue=quick');
  await smart.go(url);
  api.down = true;
  await smart.menu('quick-save');

  const save = smart.chrome().locator('.save');
  await expect(save).toHaveAttribute('title', 'Saved here, waiting for your bookmarks API (⌘⇧B)');
  await expect.poll(() => smart.menuItem('saves-waiting')).toMatchObject({ label: 'Saves Waiting (1)…' });
  expect(await lookup(url)).toBeNull();
  await smart.snapshot('20-waiting');

  api.down = false;
  await smart.menu('saves-waiting');
  const card = await smart.overlay();
  await expect(card.getByRole('list', { name: 'Saves waiting' }).getByRole('listitem')).toHaveCount(1);
  await expect(card.getByRole('listitem')).toContainText('Tuning Postgres');
  await expect(card.getByRole('listitem')).toContainText('tried once');
  await smart.snapshot('21-saves-waiting');
  await card.getByRole('button', { name: 'Retry all' }).click();

  await expect.poll(() => tagsOf(url)).toEqual([]);
  await expect(save).toHaveAttribute('title', 'Saved, untagged (⌘⇧B)');
  await expect.poll(() => smart.overlayOpen()).toBe(false); // nothing left to show
  await expect.poll(() => smart.menuItem('saves-waiting')).toBeNull();
});

test('the save sheet takes a save while the API is away, with your tags as last fetched', async ({ api, smart }) => {
  // A tag in your vocabulary, and a sheet opened once while the API was there to fetch it.
  const known = SITE('/article.html?queue=vocabulary');
  await fetch(`${API()}/api/v1/bookmarks`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${TOKEN()}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: known, tags: ['queued-vocabulary'] }),
  });
  await smart.go(known);
  await smart.menu('save-sheet');
  await expect((await smart.overlay()).getByText('Saved', { exact: true })).toBeVisible();
  await smart.menu('close-tab');

  api.down = true;
  const url = SITE('/second.html?queue=sheet');
  await smart.go(url);
  await smart.menu('save-sheet');
  const sheet = await smart.overlay();
  await expect(sheet.getByRole('status')).toHaveText(
    'Can’t reach your bookmarks API. This page will be saved when it’s back.',
  );
  await expect(sheet.getByText('Not known offline')).toBeVisible();
  await sheet.getByLabel('Tags', { exact: true }).fill('queued-v');
  await expect(sheet.getByRole('list', { name: 'Suggestions' }).getByRole('button').first()).toContainText(
    'queued-vocabulary',
  );
  await sheet.getByLabel('Tags', { exact: true }).press('Tab');
  await smart.snapshot('22-sheet-offline');
  await sheet.getByLabel('Tags', { exact: true }).press('Enter');
  await expect.poll(() => smart.overlayOpen()).toBe(false);
  const save = smart.chrome().locator('.save');
  await expect(save).toHaveAttribute(
    'title',
    'Saved here with queued-vocabulary, waiting for your bookmarks API (⌘⇧B)',
  );

  // The next thing you ask of the API takes the waiting save with it.
  api.down = false;
  await smart.go(SITE('/links.html?queue=sheet'));
  await smart.menu('save-sheet');
  await expect((await smart.overlay()).getByText('Not saved yet')).toBeVisible();
  await expect.poll(() => tagsOf(url)).toEqual(['queued-vocabulary']);
  expect(api.requests.filter((r) => r === 'POST /api/v1/bookmarks')).toHaveLength(1); // once
});

test('saves still waiting at quit are delivered at the next launch', async ({ api, smart }) => {
  const url = SITE('/links.html?queue=launch');
  await smart.go(url);
  api.down = true;
  await smart.menu('quick-save');
  await expect.poll(() => smart.menuItem('saves-waiting')).not.toBeNull();
  await smart.close();

  api.down = false;
  const next = await BrowserApp.launch(smart.profile);
  try {
    await expect.poll(() => tagsOf(url)).toEqual([]);
    await expect.poll(() => next.menuItem('saves-waiting')).toBeNull();
  } finally {
    await next.close();
  }
});

test('a save the API refuses when it is back waits for you to fix it, or drop it', async ({ api, smart }) => {
  const url = SITE('/second.html?queue=refused');
  await smart.go(url);
  api.down = true;
  await smart.menu('save-sheet');
  const sheet = await smart.overlay();
  await sheet.getByLabel('Tags', { exact: true }).fill('first-try');
  await sheet.getByLabel('Tags', { exact: true }).press('Enter');
  await expect.poll(() => smart.overlayOpen()).toBe(false);

  // Back, and saying no.
  api.down = false;
  api.refuseSaves = true;
  await expect.poll(() => smart.menuItem('saves-waiting')).not.toBeNull(); // the menu follows within a second
  await smart.menu('saves-waiting');
  const card = await smart.overlay();
  await card.getByRole('button', { name: 'Retry all' }).click();
  await expect(card.getByRole('listitem')).toContainText('Refused: Tag names cannot contain a comma.');
  await smart.snapshot('23-refused');
  await card.getByRole('button', { name: 'Close' }).click();
  const save = smart.chrome().locator('.save');
  await expect(save).toHaveAttribute(
    'title',
    'Your bookmarks API refused this save: Tag names cannot contain a comma. (⌘⇧B)',
  );

  // Fixed in the sheet: its tags are the ones to edit, and saving replaces them.
  api.refuseSaves = false;
  await smart.menu('save-sheet');
  const fix = await smart.overlay();
  await expect(fix.getByText('Refused', { exact: true })).toBeVisible();
  await expect(fix.getByRole('alert')).toContainText('Tag names cannot contain a comma.');
  await expect(fix.getByLabel('Tags', { exact: true })).toHaveValue('first-try');
  await fix.getByLabel('Tags', { exact: true }).fill('fixed');
  await fix.getByRole('button', { name: 'Save again' }).click();
  await expect(save).toHaveAttribute('title', 'Saved with fixed (⌘⇧B)');
  expect(await tagsOf(url)).toEqual(['fixed']);
  await expect.poll(() => smart.menuItem('saves-waiting')).toBeNull();

  // Or dropped: nothing is sent for it.
  const dropped = SITE('/untitled.html?queue=dropped');
  await smart.go(dropped);
  api.down = true;
  await smart.menu('quick-save');
  await expect.poll(() => smart.menuItem('saves-waiting')).not.toBeNull();
  await smart.menu('saves-waiting');
  await (await smart.overlay()).getByRole('button', { name: 'Drop' }).click();
  await expect.poll(() => smart.overlayOpen()).toBe(false);
  await expect(save).toHaveAttribute('title', 'Save this page with tags (⌘⇧B)');
  api.down = false;
  expect(await lookup(dropped)).toBeNull();
});
