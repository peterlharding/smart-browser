/**
 * The browser under test: launched from its build with a throwaway profile, so it never
 * touches the one you browse with, and helpers to drive it the way a person would.
 */

import { _electron, test as base, expect, type ElectronApplication, type Locator, type Page } from '@playwright/test';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const APP = fileURLToPath(new URL('../../', import.meta.url));
const SNAPSHOTS = join(APP, 'test-results', 'snapshots');

// On Linux (CI): the secret store is GNOME Keyring, which Chromium picks by itself only in
// a desktop session, so it is named; and xvfb has no GPU, so capturing a page for a
// snapshot fails unless Chromium renders in software.
const LINUX_SWITCHES = ['--password-store=gnome-libsecret', '--disable-gpu'];

export const API = () => process.env.E2E_API_URL!;
export const TOKEN = () => process.env.E2E_API_TOKEN!;
export const SITE = (path: string) => `${process.env.E2E_SITE!}${path}`;

export class BrowserApp {
  /** Everything the main process printed, attached to a failing test. */
  readonly output: string[] = [];

  constructor(
    readonly app: ElectronApplication,
    readonly profile: string,
  ) {}

  static async launch(profile = mkdtempSync(join(tmpdir(), 'smart-browser-e2e-'))): Promise<BrowserApp> {
    const app = await _electron.launch({
      cwd: APP,
      args: ['.', ...(process.platform === 'linux' ? LINUX_SWITCHES : [])],
      env: { ...process.env, SMART_BROWSER_USER_DATA: profile },
    });
    const browser = new BrowserApp(app, profile);
    const record = (chunk: Buffer) => browser.output.push(String(chunk));
    app.process().stdout?.on('data', record);
    app.process().stderr?.on('data', record);
    const chrome = await browser.waitForPage('smart://ui/chrome.html');
    await chrome.waitForSelector('.toolbar');
    await browser.waitForPage('smart://ui/overlay.html');
    return browser;
  }

  chrome(): Page {
    return this.page('smart://ui/chrome.html');
  }

  /**
   * The overlay, fetched afresh: it is detached from the window whenever a card closes,
   * and Playwright takes a detached view's page for closed, so a page object from an
   * earlier open is dead.
   */
  async overlay(): Promise<Page> {
    await expect.poll(() => this.overlayOpen(), { message: 'no card is open' }).toBe(true);
    return this.waitForPage('smart://ui/overlay.html');
  }

  /** The tab showing *url*, once it does. Tests use distinct URLs, so this is unambiguous. */
  async tab(url: string): Promise<Page> {
    const page = await this.waitForPage(url);
    await page.waitForLoadState();
    return page;
  }

  /** Views appear after launch, and a view's first URL is about:blank until it loads. */
  async waitForPage(url: string, timeout = 10_000): Promise<Page> {
    const deadline = Date.now() + timeout;
    for (;;) {
      const found = this.app.windows().find((p) => p.url() === url);
      if (found) return found;
      if (Date.now() > deadline) return this.page(url); // throws, listing what there is
      await new Promise((r) => setTimeout(r, 50));
    }
  }

  private page(url: string): Page {
    const found = this.app.windows().find((p) => p.url() === url);
    if (!found) throw new Error(`no page at ${url}; have ${this.app.windows().map((p) => p.url()).join(', ')}`);
    return found;
  }

  /** Trigger a menu item, as its keyboard shortcut would. */
  async menu(id: string): Promise<void> {
    await this.app.evaluate(({ Menu }, itemId) => {
      const item = Menu.getApplicationMenu()?.getMenuItemById(itemId);
      if (!item) throw new Error(`no menu item ${itemId}`);
      item.click();
    }, id);
  }

  async accelerator(id: string): Promise<string | undefined> {
    return this.app.evaluate(
      ({ Menu }, itemId) => Menu.getApplicationMenu()?.getMenuItemById(itemId)?.accelerator ?? undefined,
      id,
    );
  }

  /**
   * Navigate the active tab as a person would, through the omnibox, and wait for the page
   * to load, as a person would before doing anything with it.
   */
  async go(url: string): Promise<Page> {
    const omnibox = this.chrome().locator('.omnibox');
    await omnibox.click();
    await omnibox.fill(url);
    await omnibox.press('Enter');
    return this.tab(url);
  }

  /** The overlay is attached to the window only while a card is open. */
  async overlayOpen(): Promise<boolean> {
    return this.app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows()[0]!;
      return win.contentView.children.some(
        (v) => (v as Electron.WebContentsView).webContents.getURL() === 'smart://ui/overlay.html',
      );
    });
  }

  async configure(apiUrl = API(), token = TOKEN()): Promise<void> {
    await this.menu('settings');
    const overlay = await this.overlay();
    await overlay.getByLabel('Bookmarks API').fill(apiUrl);
    await overlay.getByLabel('API token').fill(token);
    await overlay.getByRole('button', { name: 'Save' }).click();
    await expect.poll(() => this.overlayOpen()).toBe(false);
  }

  /**
   * Each layer of the window as a PNG, and where it sits, for looking at the result rather
   * than only asserting on it: test-results/snapshots/<name>-*.png.
   */
  async snapshot(name: string): Promise<void> {
    mkdirSync(SNAPSHOTS, { recursive: true });
    const layers = await this.app.evaluate(async ({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows()[0]!;
      const png = async (wc: Electron.WebContents) => (await wc.capturePage()).toPNG().toString('base64');
      return {
        size: win.getContentSize(),
        chrome: await png(win.webContents),
        views: await Promise.all(
          win.contentView.children.map(async (v) => ({
            bounds: v.getBounds(),
            png: await png((v as Electron.WebContentsView).webContents),
          })),
        ),
      };
    });
    writeFileSync(join(SNAPSHOTS, `${name}-chrome.png`), Buffer.from(layers.chrome, 'base64'));
    layers.views.forEach((v, i) => writeFileSync(join(SNAPSHOTS, `${name}-view${i}.png`), Buffer.from(v.png, 'base64')));
    writeFileSync(
      join(SNAPSHOTS, `${name}.json`),
      JSON.stringify({ size: layers.size, views: layers.views.map((v) => ({ bounds: v.bounds })) }),
    );
  }

  close(): Promise<void> {
    return this.app.close();
  }

  /** Close, and delete the throwaway profile: every launch makes one. */
  async dispose(): Promise<void> {
    await this.close().catch(() => undefined);
    rmSync(this.profile, { recursive: true, force: true });
  }
}

// `smart`, not `browser`: Playwright already has a fixture by that name.
export const test = base.extend<{ smart: BrowserApp }>({
  // eslint-disable-next-line no-empty-pattern
  smart: async ({}, use, testInfo) => {
    const browser = await BrowserApp.launch();
    await use(browser);
    await browser.dispose();
    if (testInfo.status !== testInfo.expectedStatus) {
      await testInfo.attach('main-process output', { body: browser.output.join(''), contentType: 'text/plain' });
    }
  },
});

/**
 * Whether *locator* is its document's focused element. Not Playwright's toBeFocused, which
 * also needs the OS window to be the key window: after a few launches in a row macOS does
 * not always make the newest one key, and that is the desktop's state, not the app's.
 */
export async function expectFocused(locator: Locator, focused = true): Promise<void> {
  await expect
    .poll(() => locator.evaluate((element) => element === element.ownerDocument.activeElement))
    .toBe(focused);
}

export { expect };
