/**
 * The browser under test: launched from its build with a throwaway profile, so it never
 * touches the one you browse with, and helpers to drive it the way a person would.
 */

import { _electron, test as base, expect, type ElectronApplication, type Locator, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const APP = fileURLToPath(new URL('../../', import.meta.url));
const SNAPSHOTS = join(APP, 'test-results', 'snapshots');

// On Linux (CI): Playwright's loader forces --password-store=basic, which a preload undoes
// (see linux-secret-store.cjs); and xvfb has no GPU, so capturing a page for a snapshot
// fails unless Chromium renders in software.
const LINUX_SWITCHES = ['-r', join(APP, 'test/e2e/linux-secret-store.cjs'), '--disable-gpu'];

export const API = () => process.env.E2E_API_URL!;
export const TOKEN = () => process.env.E2E_API_TOKEN!;
export const SITE = (path: string) => `${process.env.E2E_SITE!}${path}`;
/** The same site under another host name, for "More from this site". */
export const OTHER_SITE = (path: string) => SITE(path).replace('127.0.0.1', 'localhost');

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
      // Without this Playwright adds --no-sandbox on Linux: the tests run the browser as it
      // ships, sandboxed, which is also why CI allows unprivileged user namespaces.
      chromiumSandbox: true,
      // Chromium's switches before the app path: Electron hands everything after it to
      // the app, not to Chromium, so a switch there is silently ignored.
      args: [...(process.platform === 'linux' ? LINUX_SWITCHES : []), '.'],
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

  /**
   * Views appear after launch, and a view's first URL is about:blank until it loads. A page
   * that sets a fragment as it loads is still the page asked for.
   */
  async waitForPage(url: string, timeout = 10_000): Promise<Page> {
    const deadline = Date.now() + timeout;
    const same = (p: Page) => p.url() === url || (!url.includes('#') && p.url().split('#')[0] === url);
    for (;;) {
      const found = this.app.windows().find((p) => p.url() === url) ?? this.app.windows().find(same);
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

  /** The history page, once a tab shows it. */
  async historyPage(): Promise<Page> {
    await expect
      .poll(() => this.app.windows().some((p) => p.url().startsWith('smart://history/')), {
        message: 'no tab shows the history page',
      })
      .toBe(true);
    const page = this.app.windows().find((p) => p.url().startsWith('smart://history/'))!;
    await page.waitForSelector('.page');
    return page;
  }

  /** A menu item as the menu shows it now: it is rebuilt as history changes. */
  async menuItem(id: string): Promise<{ label: string; enabled: boolean; icon: boolean; toolTip: string } | null> {
    return this.app.evaluate(({ Menu }, itemId) => {
      const item = Menu.getApplicationMenu()?.getMenuItemById(itemId);
      if (!item) return null;
      return {
        label: item.label,
        enabled: item.enabled,
        icon: Boolean(item.icon && typeof item.icon !== 'string' && !item.icon.isEmpty()),
        toolTip: item.toolTip,
      };
    }, id);
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
    // What settles, settled: a card fading in is captured as it looks, not half there.
    // Endless animations, a tab's loading spinner say, are left running.
    await Promise.all(
      this.app.windows().map((page) =>
        page
          .evaluate(() =>
            Promise.all(
              document
                .getAnimations()
                .filter((a) => a.effect?.getTiming().iterations !== Infinity)
                .map((a) => a.finished),
            ).then(() => undefined),
          )
          .catch(() => undefined), // a page mid-navigation has nothing to wait for
      ),
    );
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

  /**
   * Quit, as the menu's Quit would. An app that does not quit is a bug, not a slow test:
   * after 10 seconds it is killed, and the failure carries what it printed.
   */
  async close(): Promise<void> {
    const quit = this.app.close().then(() => 'quit' as const);
    const stuck = new Promise<'stuck'>((resolve) => setTimeout(() => resolve('stuck'), 10_000).unref());
    if ((await Promise.race([quit, stuck])) === 'quit') return;
    const pid = this.app.process().pid;
    let stack = '';
    try {
      if (process.platform === 'darwin' && pid) stack = execFileSync('sample', [String(pid), '2'], { encoding: 'utf8' });
    } catch {
      // no sample, only the output
    }
    this.app.process().kill('SIGKILL');
    throw new Error(`The app did not quit within 10 seconds.
--- output ---
${this.output.join('').slice(-4000)}
--- sample ---
${stack.slice(0, 20000)}`);
  }

  /** Close, and delete the throwaway profile: every launch makes one. */
  async dispose(): Promise<void> {
    try {
      await this.close();
    } catch (error) {
      // Closing an app that already quit is fine; one that will not quit is a failure.
      if (error instanceof Error && error.message.startsWith('The app did not quit')) throw error;
    } finally {
      rmSync(this.profile, { recursive: true, force: true });
    }
  }
}

/**
 * A stand-in for the API's access log: a proxy in front of the real API that records each
 * request, so a test can say what the browser sent, including at launch, before any code
 * in the test could have wrapped anything in the app.
 */
export interface ApiRecorder {
  url: string;
  /** What reached the API through the proxy, as "METHOD /path". */
  requests: string[];
  /** Refuse every connection, as an API that is not running does (ADR 0017). */
  down: boolean;
  /** Answer saves with the API's own 422, as it would a tag it cannot accept. */
  refuseSaves: boolean;
  close(): Promise<void>;
}

export async function recordApi(): Promise<ApiRecorder> {
  const requests: string[] = [];
  const server = createServer((request, response) => {
    if (recorder.down) {
      request.socket.destroy();
      return;
    }
    const chunks: Buffer[] = [];
    request.on('data', (chunk: Buffer) => chunks.push(chunk));
    request.on('end', () => {
      const path = new URL(request.url ?? '/', 'http://api').pathname;
      requests.push(`${request.method} ${path}`);
      if (recorder.refuseSaves && request.method === 'POST' && path === '/api/v1/bookmarks') {
        response.writeHead(422, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ detail: 'Tag names cannot contain a comma.' }));
        return;
      }
      const headers = new Headers();
      for (const name of ['authorization', 'content-type', 'accept']) {
        const value = request.headers[name];
        if (typeof value === 'string') headers.set(name, value);
      }
      const body = chunks.length ? Buffer.concat(chunks) : undefined;
      void fetch(`${API()}${request.url}`, { method: request.method, headers, body }).then(
        async (answer) => {
          response.writeHead(answer.status, { 'Content-Type': answer.headers.get('content-type') ?? 'text/plain' });
          response.end(Buffer.from(await answer.arrayBuffer()));
        },
        () => response.writeHead(502).end(),
      );
    });
  });
  const recorder: ApiRecorder = {
    url: '',
    requests,
    down: false,
    refuseSaves: false,
    close: () =>
      new Promise((resolve) => {
        server.closeAllConnections();
        server.close(() => resolve());
      }),
  };
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  recorder.url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return recorder;
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
