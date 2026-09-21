/**
 * The browser window: its three layers, its tabs, and the requests its UI makes (ADR 0015).
 *
 *   1. the chrome     the window's own contents: tab strip and toolbar, CHROME_HEIGHT tall
 *   2. tabs           one WebContentsView each below the chrome; only the active one attached
 *   3. the overlay    a transparent WebContentsView over the page area, attached only while
 *                     the save sheet or settings are open, since anything the chrome drew
 *                     there would be hidden under the page
 */

import { BrowserWindow, WebContentsView, session } from 'electron';
import { join } from 'node:path';

import {
  API_CONTRACT_VERSION,
  Channels,
  type Bookmark,
  type ChromeState,
  type ConnectionReport,
  type OverlayState,
  type SavedState,
  type SettingsInput,
} from '../shared/ipc';
import { Api, ApiError } from './api';
import { Lookups } from './lookups';
import { resolveInput } from './omnibox';
import { readSession, writeSession } from './session';
import type { SettingsStore } from './settings';
import { Tab } from './tabs';

export const CHROME_HEIGHT = 80;
const BROWSE_PARTITION = 'persist:browse';

export interface Paths {
  preload: string;
  sessionFile: string;
}

export class Browser {
  readonly window: BrowserWindow;
  private readonly tabs: Tab[] = [];
  private activeId: number | null = null;
  private readonly overlay: WebContentsView;
  private overlayState: OverlayState | null = null;
  private saved: SavedState = { kind: 'unknown' };
  private focusOmnibox = 0;
  private lookupSeq = 0;
  private readonly lookups = new Lookups();
  private contractProblem: string | null = null;
  private sessionTimer: NodeJS.Timeout | null = null;

  constructor(
    private readonly settings: SettingsStore,
    private readonly paths: Paths,
  ) {
    this.window = new BrowserWindow({
      width: 1280,
      height: 860,
      minWidth: 560,
      minHeight: 360,
      show: false,
      title: 'Smart-Browser',
      titleBarStyle: 'hiddenInset',
      trafficLightPosition: { x: 14, y: 12 },
      backgroundColor: '#e9ebef',
      webPreferences: {
        preload: join(paths.preload, 'chrome.cjs'),
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
      },
    });
    lockToAppFiles(this.window.webContents);
    void this.window.loadURL('smart://ui/chrome.html');
    // The chrome's views share one window, so moving focus to a page or the overlay fires
    // no DOM blur in the chrome, and its omnibox would keep its caret and focus ring.
    this.window.webContents.on('blur', () => {
      if (!this.window.isDestroyed()) this.window.webContents.send(Channels.chrome.blur);
    });

    this.overlay = new WebContentsView({
      webPreferences: {
        preload: join(paths.preload, 'overlay.cjs'),
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
      },
    });
    this.overlay.setBackgroundColor('#00000000');
    lockToAppFiles(this.overlay.webContents);
    void this.overlay.webContents.loadURL('smart://ui/overlay.html');

    this.window.on('resize', () => this.layout());
    this.window.once('ready-to-show', () => this.window.show());
    this.window.webContents.once('did-finish-load', () => this.pushChrome());
    // Saved on close, while the tabs still exist; 'closed' is too late.
    this.window.on('close', () => this.saveSession());
    this.window.on('closed', () => this.dispose());

    this.restore();
    void this.checkContract();
  }

  // --- tabs ------------------------------------------------------------------------

  newTab(url = 'about:blank', { activate = true } = {}): Tab {
    const tab = new Tab(session.fromPartition(BROWSE_PARTITION), {
      changed: () => this.pushChrome(),
      navigated: (t) => {
        if (t.id === this.activeId) void this.refreshSaved();
        this.saveSessionSoon();
      },
      openTab: (target, opener) => {
        const index = this.tabs.indexOf(opener);
        const created = this.newTab(target);
        this.move(created.id, index + 1);
      },
    });
    this.tabs.push(tab);
    tab.load(url);
    if (activate) this.activate(tab.id);
    this.pushChrome();
    this.saveSessionSoon();
    return tab;
  }

  close(id: number): void {
    const index = this.tabs.findIndex((t) => t.id === id);
    const tab = this.tabs[index];
    if (!tab) return;
    if (this.tabs.length === 1) {
      this.window.close();
      return;
    }
    this.tabs.splice(index, 1);
    if (this.activeId === id) {
      const next = this.tabs[Math.min(index, this.tabs.length - 1)];
      if (next) this.activate(next.id);
    }
    this.window.contentView.removeChildView(tab.view);
    tab.destroy();
    this.pushChrome();
    this.saveSessionSoon();
  }

  activate(id: number): void {
    const tab = this.tabs.find((t) => t.id === id);
    if (!tab) return;
    const previous = this.active();
    if (previous && previous !== tab) this.window.contentView.removeChildView(previous.view);
    this.activeId = id;
    this.window.contentView.addChildView(tab.view, 0);
    if (this.overlayState) this.closeOverlay();
    this.layout();
    if (tab.isBlank) this.focusOmnibox += 1;
    else tab.view.webContents.focus();
    this.pushChrome();
    void this.refreshSaved();
    this.saveSessionSoon();
  }

  /** Activate by position, as ⌘1–⌘8 do; ⌘9 is always the last tab. */
  activateIndex(index: number): void {
    const tab = index === -1 ? this.tabs.at(-1) : this.tabs[index];
    if (tab) this.activate(tab.id);
  }

  cycle(step: 1 | -1): void {
    const index = this.tabs.findIndex((t) => t.id === this.activeId);
    const next = this.tabs[(index + step + this.tabs.length) % this.tabs.length];
    if (next) this.activate(next.id);
  }

  move(id: number, index: number): void {
    const from = this.tabs.findIndex((t) => t.id === id);
    if (from === -1) return;
    const [tab] = this.tabs.splice(from, 1);
    if (!tab) return;
    this.tabs.splice(Math.max(0, Math.min(index, this.tabs.length)), 0, tab);
    this.pushChrome();
    this.saveSessionSoon();
  }

  navigate(input: string): void {
    const url = resolveInput(input, this.settings.searchEngine);
    const tab = this.active();
    if (!url || !tab) return;
    tab.load(url);
    tab.view.webContents.focus();
  }

  back(): void {
    this.active()?.view.webContents.navigationHistory.goBack();
  }

  forward(): void {
    this.active()?.view.webContents.navigationHistory.goForward();
  }

  reload(): void {
    const tab = this.active();
    if (!tab) return;
    // Reloading is asking again, so it asks the API again too: the page may have been
    // saved from somewhere else, the extension say, since the answer was kept.
    this.lookups.forget(tab.url);
    tab.view.webContents.reload();
  }

  stop(): void {
    this.active()?.view.webContents.stop();
  }

  closeActive(): void {
    if (this.overlayState) return this.closeOverlay();
    if (this.activeId !== null) this.close(this.activeId);
  }

  toggleDevTools(): void {
    this.active()?.view.webContents.toggleDevTools();
  }

  focusLocation(): void {
    this.focusOmnibox += 1;
    this.pushChrome();
  }

  private active(): Tab | undefined {
    return this.tabs.find((t) => t.id === this.activeId);
  }

  private layout(): void {
    const { width, height } = this.window.getContentBounds();
    const page = { x: 0, y: CHROME_HEIGHT, width, height: Math.max(0, height - CHROME_HEIGHT) };
    this.active()?.view.setBounds(page);
    this.overlay.setBounds(page);
  }

  // --- the chrome's state ------------------------------------------------------------

  private pushChrome(): void {
    if (this.window.isDestroyed()) return;
    const history = this.active()?.view.webContents.navigationHistory;
    const state: ChromeState = {
      tabs: this.tabs.map((t) => t.state()),
      activeId: this.activeId,
      canGoBack: history?.canGoBack() ?? false,
      canGoForward: history?.canGoForward() ?? false,
      saved: this.saved,
      focusOmnibox: this.focusOmnibox,
    };
    this.window.webContents.send(Channels.chrome.state, state);
  }

  private api(): Api | null {
    const token = this.settings.token();
    if (!this.settings.apiUrl || !token) return null;
    return new Api({ baseUrl: this.settings.apiUrl, token });
  }

  /** Whether the active page is in your library, for the toolbar's indicator. */
  private async refreshSaved(): Promise<void> {
    const seq = ++this.lookupSeq;
    const tab = this.active();
    const api = this.api();
    const set = (saved: SavedState) => {
      if (seq !== this.lookupSeq) return; // a newer page has been asked about since
      this.saved = saved;
      this.pushChrome();
    };
    if (!tab || !/^https?:/i.test(tab.url)) return set({ kind: 'not-web' });
    if (!api) return set({ kind: 'unconfigured' });
    if (this.contractProblem) return set({ kind: 'unavailable', reason: this.contractProblem });
    const url = tab.url;
    try {
      set(
        await this.lookups.lookup(url, async () => {
          const found = await api.lookup(url);
          return found ? { kind: 'saved', tags: found.tags } : { kind: 'unsaved' };
        }),
      );
    } catch (error) {
      set({ kind: 'unavailable', reason: messageOf(error) });
    }
  }

  /** ADR 0005: the browser asserts the API's contract before it saves anything. */
  private async checkContract(): Promise<void> {
    const api = this.api();
    this.contractProblem = null;
    this.lookups.forget(); // new settings may name a different API, with different answers
    if (api) {
      try {
        const health = await api.health();
        if (health.contract !== API_CONTRACT_VERSION) {
          this.contractProblem =
            `The API speaks contract ${health.contract} and this browser speaks ` +
            `${API_CONTRACT_VERSION}, so saving is off until one of them is updated.`;
        }
      } catch {
        // Unreachable is reported per request, where it can be retried.
      }
    }
    await this.refreshSaved();
  }

  // --- saving --------------------------------------------------------------------------

  async openSaveSheet(): Promise<void> {
    const tab = this.active();
    if (!tab) return;
    if (!/^https?:/i.test(tab.url)) return;
    const api = this.api();
    if (!api) return this.openSettings();
    const base = { mode: 'save' as const, url: tab.url, title: tab.title };
    if (this.contractProblem) {
      return this.showOverlay({ ...base, bookmark: null, vocabulary: [], error: this.contractProblem });
    }
    try {
      const [bookmark, vocabulary] = await Promise.all([
        api.lookup(tab.url),
        api.tags().catch(() => []), // no vocabulary costs autocomplete, not saving
      ]);
      this.lookups.remember(tab.url, bookmark ? { kind: 'saved', tags: bookmark.tags } : { kind: 'unsaved' });
      this.showOverlay({ ...base, bookmark, vocabulary, error: null });
    } catch (error) {
      this.showOverlay({ ...base, bookmark: null, vocabulary: [], error: messageOf(error) });
    }
  }

  async quickSave(): Promise<void> {
    const tab = this.active();
    const api = this.api();
    if (!tab || !/^https?:/i.test(tab.url)) return;
    if (!api) return this.openSettings();
    try {
      const saved = await api.save({ url: tab.url, title: tab.title, tags: [] });
      this.showSaved(tab.url, saved);
    } catch (error) {
      this.saved = { kind: 'unavailable', reason: messageOf(error) };
      this.pushChrome();
    }
  }

  /** What a save or a tag removal established about *url*, kept, and shown if it is open. */
  private showSaved(url: string, bookmark: Bookmark): void {
    const saved = { kind: 'saved' as const, tags: bookmark.tags };
    this.lookups.remember(url, saved);
    if (this.active()?.url !== url) return;
    // A lookup started before this save may still be in flight, and its answer ("not
    // saved") is now stale: moving the sequence on makes it discard itself.
    this.lookupSeq += 1;
    this.saved = saved;
    this.pushChrome();
  }

  // --- the overlay ---------------------------------------------------------------------

  openSettings(): void {
    this.showOverlay({
      mode: 'settings',
      apiUrl: this.settings.apiUrl,
      hasToken: this.settings.hasToken,
      searchEngine: this.settings.searchEngine,
      tokenStorage: this.settings.tokenStorageAvailable ? 'keychain' : 'unavailable',
    });
  }

  private showOverlay(state: OverlayState): void {
    this.overlayState = state;
    this.layout();
    this.window.contentView.addChildView(this.overlay);
    this.overlay.webContents.send(Channels.overlay.state, state);
    this.overlay.webContents.focus();
  }

  closeOverlay(): void {
    if (!this.overlayState) return;
    this.overlayState = null;
    this.window.contentView.removeChildView(this.overlay);
    this.active()?.view.webContents.focus();
  }

  /** Which of this window's own views *contents* is, if either: IPC answers only those. */
  owns(contents: Electron.WebContents): 'chrome' | 'overlay' | null {
    if (!this.window.isDestroyed() && contents === this.window.webContents) return 'chrome';
    if (contents === this.overlay.webContents) return 'overlay';
    return null;
  }

  async saveFromSheet(tags: string[]): Promise<string | null> {
    const sheet = this.overlayState;
    const api = this.api();
    if (sheet?.mode !== 'save' || !api) return 'Nothing to save.';
    try {
      const saved = await api.save({ url: sheet.url, title: sheet.title, tags });
      this.closeOverlay();
      this.showSaved(sheet.url, saved);
      return null;
    } catch (error) {
      return messageOf(error);
    }
  }

  async removeTagFromSheet(tag: string): Promise<Bookmark | string> {
    const sheet = this.overlayState;
    const api = this.api();
    if (sheet?.mode !== 'save' || !sheet.bookmark || !api) return 'Nothing to remove from.';
    try {
      const updated = await api.removeTag(sheet.bookmark.id, tag);
      this.overlayState = { ...sheet, bookmark: updated };
      this.showSaved(sheet.url, updated);
      return updated;
    } catch (error) {
      return messageOf(error);
    }
  }

  async saveSettings(input: SettingsInput): Promise<void> {
    this.settings.update(input);
    this.closeOverlay();
    await this.checkContract();
  }

  async testConnection(input: SettingsInput): Promise<ConnectionReport> {
    const token = input.token === undefined ? this.settings.token() : input.token.trim();
    if (!input.apiUrl.trim()) return { ok: false, reason: 'Enter the API address.' };
    if (!token) return { ok: false, reason: 'Enter the API token.' };
    const api = new Api({ baseUrl: input.apiUrl.trim(), token });
    try {
      const health = await api.health();
      await api.tags(); // health needs no token; this proves the token works
      return {
        ok: true,
        version: health.version,
        contract: health.contract,
        schema: health.schema_revision ?? null,
        compatible: health.contract === API_CONTRACT_VERSION,
      };
    } catch (error) {
      return { ok: false, reason: messageOf(error) };
    }
  }

  // --- session ---------------------------------------------------------------------------

  private restore(): void {
    const saved = readSession(this.paths.sessionFile);
    if (!saved) {
      this.newTab();
      return;
    }
    for (const url of saved.urls) this.newTab(url, { activate: false });
    const active = this.tabs[saved.active];
    if (active) this.activate(active.id);
  }

  private saveSessionSoon(): void {
    if (this.sessionTimer) clearTimeout(this.sessionTimer);
    this.sessionTimer = setTimeout(() => this.saveSession(), 400);
  }

  saveSession(): void {
    if (this.sessionTimer) clearTimeout(this.sessionTimer);
    this.sessionTimer = null;
    const urls = this.tabs.map((t) => t.url);
    const active = Math.max(0, this.tabs.findIndex((t) => t.id === this.activeId));
    writeSession(this.paths.sessionFile, { urls, active });
  }

  private dispose(): void {
    for (const tab of this.tabs) tab.destroy();
    this.overlay.webContents.close();
  }
}

/** The chrome and the overlay show the app's own files and nothing else (ADR 0015). */
function lockToAppFiles(contents: Electron.WebContents): void {
  contents.on('will-navigate', (event) => event.preventDefault());
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
}

function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : String(error);
}
