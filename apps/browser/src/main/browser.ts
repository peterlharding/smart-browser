/**
 * The browser window: its three layers, its tabs, and the requests its UI makes (ADR 0015).
 *
 *   1. the chrome     the window's own contents: tab strip and toolbar, CHROME_HEIGHT tall
 *   2. tabs           one WebContentsView each below the chrome; only the active one attached
 *   3. the overlay    a transparent WebContentsView over the page area, attached only while
 *                     the save sheet or settings are open, since anything the chrome drew
 *                     there would be hidden under the page
 *
 * The API is contacted only when you ask for something: the save sheet, a quick save,
 * removing a tag, testing settings. Browsing sends it nothing (ADR 0016); where you have
 * been is kept locally, in History.
 */

import { BrowserWindow, WebContentsView, session } from 'electron';
import { join } from 'node:path';

import {
  API_CONTRACT_VERSION,
  Channels,
  type Bookmark,
  type ChromeState,
  type ClearInput,
  type ConnectionReport,
  type Delivery,
  type HistoryQuery,
  type HistoryResult,
  type HistoryView,
  type OpenDisposition,
  type OverlayState,
  type SavedState,
  type SettingsInput,
} from '../shared/ipc';
import { Api, ApiError, isOffline } from './api';
import type { Connection } from './connection';
import type { History } from './history';
import { resolveInput } from './omnibox';
import type { SaveQueue } from './queue';
import { readSession, writeSession } from './session';
import type { SettingsStore } from './settings';
import { Tab, lockToAppFiles, type Navigation, type TabEnvironment } from './tabs';
import { hostOf, historyUrl, isRecordable, isWeb, pageKey } from './urls';

export const CHROME_HEIGHT = 80;
const BROWSE_PARTITION = 'persist:browse';
const FAVICON_CACHE = 200;

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
  private readonly environment: TabEnvironment;
  private focusOmnibox = 0;
  /** The last action on a page that failed, shown on the save button while it is open. */
  private problem: { page: string; reason: string } | null = null;
  private readonly favicons = new Map<string, Promise<string | null>>();
  private readonly stopListening: () => void;
  private historyTimer: NodeJS.Timeout | null = null;
  private sessionTimer: NodeJS.Timeout | null = null;
  private disposed = false;

  constructor(
    private readonly settings: SettingsStore,
    private readonly paths: Paths,
    private readonly history: History,
    private readonly connection: Connection,
    private readonly queue: SaveQueue,
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

    this.environment = { browse: session.fromPartition(BROWSE_PARTITION), preload: paths.preload };
    this.stopListening = history.onChange(() => this.historyChanged());

    this.window.on('resize', () => this.layout());
    this.window.once('ready-to-show', () => this.window.show());
    this.window.webContents.once('did-finish-load', () => this.pushChrome());
    // Saved on close, while the tabs still exist; 'closed' is too late.
    this.window.on('close', () => this.saveSession());
    this.window.on('closed', () => this.dispose());

    this.restore();
  }

  // --- tabs ------------------------------------------------------------------------

  newTab(
    url = 'about:blank',
    { activate = true, index, navigation }: { activate?: boolean; index?: number; navigation?: Navigation } = {},
  ): Tab {
    const tab = new Tab(
      this.environment,
      {
        changed: () => this.pushChrome(),
        navigated: (t) => {
          if (t.id === this.activeId) this.problem = null;
          this.pushChrome();
          this.saveSessionSoon();
        },
        openTab: (target, opener) => {
          this.newTab(target, { index: this.tabs.indexOf(opener) + 1 });
        },
        visited: (t, visited) => {
          this.history.recordVisit(visited, t.pageTitle);
          if (t.favicon) this.keepFavicon(visited, t.favicon); // pushState keeps the page's icon
        },
        titled: (t) => {
          if (t.pageTitle && isRecordable(t.url)) this.history.update(t.url, { title: t.pageTitle });
        },
        favicon: (_t, page, favicon) => this.keepFavicon(page, favicon),
        replaced: (t, old) => {
          if (t.id !== this.activeId) return;
          this.window.contentView.removeChildView(old);
          this.window.contentView.addChildView(t.view, 0);
          this.layout();
          this.focusPage(t);
        },
      },
      url,
      navigation,
    );
    if (index === undefined) this.tabs.push(tab);
    else this.tabs.splice(Math.max(0, Math.min(index, this.tabs.length)), 0, tab);
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
    // Remembered for Reopen Closed Tab. Closing the last tab closes the window instead,
    // and the next window reopens its tabs from the session.
    if (!tab.isBlank) {
      this.history.pushClosed({ url: tab.url, title: tab.title, index, navigation: tab.navigation() });
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

  /** ⇧⌘T, or an item of Recently Closed: the tab back where it was, with its history. */
  reopenClosed(id?: number): void {
    const closed = this.history.takeClosed(id);
    if (closed) this.newTab(closed.url, { index: closed.index, navigation: closed.navigation });
  }

  activate(id: number): void {
    const tab = this.tabs.find((t) => t.id === id);
    if (!tab) return;
    const previous = this.active();
    if (previous && previous !== tab) this.window.contentView.removeChildView(previous.view);
    this.activeId = id;
    this.problem = null;
    this.window.contentView.addChildView(tab.view, 0);
    if (this.overlayState) this.closeOverlay();
    this.layout();
    if (tab.isBlank) this.focusOmnibox += 1;
    else this.focusPage(tab);
    this.pushChrome();
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
    if (url) this.open(url);
  }

  /** Show *url* in the active tab, as a page from the History menu opens. */
  open(url: string): void {
    const tab = this.active();
    if (!tab) return;
    tab.load(url);
    this.focusPage(tab);
  }

  /**
   * Give the page the keyboard. The omnibox lets go as well: a page opened from the menu
   * into a new tab, whose omnibox was waiting to be typed in, would otherwise keep it
   * editing an empty address over a page that has one.
   */
  private focusPage(tab: Tab): void {
    tab.view.webContents.focus();
    this.releaseOmnibox();
  }

  /**
   * The chrome hears of focus leaving it from the OS, which says nothing while the window
   * is not the frontmost one, so whatever takes the keyboard also says so directly.
   */
  private releaseOmnibox(): void {
    if (!this.window.isDestroyed()) this.window.webContents.send(Channels.chrome.blur);
  }

  back(): void {
    this.active()?.goBack();
  }

  forward(): void {
    this.active()?.goForward();
  }

  reload(): void {
    this.active()?.view.webContents.reload();
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
    const tab = this.active();
    const state: ChromeState = {
      tabs: this.tabs.map((t) => t.state()),
      activeId: this.activeId,
      canGoBack: tab?.canGoBack ?? false,
      canGoForward: tab?.canGoForward ?? false,
      saved: this.savedState(),
      focusOmnibox: this.focusOmnibox,
    };
    this.window.webContents.send(Channels.chrome.state, state);
  }

  /** The save button, from what this browser knows: it never asks the API (ADR 0016). */
  private savedState(): SavedState {
    const tab = this.active();
    if (!tab || !isWeb(tab.url)) return { kind: 'not-web' };
    if (!this.connection.api()) return { kind: 'unconfigured' };
    const contractProblem = this.connection.problem();
    if (contractProblem) return { kind: 'unavailable', reason: contractProblem };
    const saved = this.history.savedTags(tab.url);
    const pending = this.history.pendingFor(tab.url);
    if (pending?.refused) return { kind: 'refused', reason: pending.lastError ?? 'The API refused this save.' };
    if (pending) return { kind: 'waiting', tags: [...new Set([...(saved ?? []), ...pending.tags])] };
    if (this.problem?.page === pageKey(tab.url)) return { kind: 'unavailable', reason: this.problem.reason };
    return saved ? { kind: 'saved', tags: saved } : { kind: 'savable' };
  }

  /**
   * The API for an action you asked for (see Connection.connect). Any save still waiting
   * goes too: an action is a moment the API is wanted, and may well be there (ADR 0017).
   */
  private async connect(): Promise<Api | string | null> {
    void this.queue.flush();
    return this.connection.connect();
  }

  // --- saving --------------------------------------------------------------------------

  async openSaveSheet(): Promise<void> {
    const tab = this.active();
    if (!tab || !isWeb(tab.url)) return;
    const url = tab.url;
    const api = await this.connect();
    if (api === null) return this.openSettings();
    const base = {
      mode: 'save' as const,
      url,
      title: tab.title,
      offline: false,
      known: null,
      pending: this.history.pendingFor(url),
    };
    if (typeof api === 'string') {
      this.pushChrome();
      return this.showOverlay({ ...base, bookmark: null, vocabulary: [], error: api });
    }
    try {
      const [bookmark, vocabulary] = await Promise.all([
        api.lookup(url),
        api.tags().then(
          (tags) => (this.history.keepVocabulary(tags), tags),
          () => this.history.vocabulary(), // no vocabulary costs autocomplete, not saving
        ),
      ]);
      // What the API said is now known here too: saved from the extension, or removed.
      if (bookmark) this.history.markSaved(url, bookmark.tags);
      else this.history.markUnsaved(url);
      this.showOverlay({ ...base, bookmark, vocabulary, error: null });
    } catch (error) {
      if (!isOffline(error)) {
        return this.showOverlay({ ...base, bookmark: null, vocabulary: [], error: messageOf(error) });
      }
      // Away: the sheet still takes a save, with what is known here (ADR 0017).
      this.showOverlay({
        ...base,
        bookmark: null,
        vocabulary: this.history.vocabulary(),
        error: null,
        offline: true,
        known: this.history.savedTags(url),
      });
    }
  }

  async quickSave(): Promise<void> {
    const tab = this.active();
    if (!tab || !isWeb(tab.url)) return;
    const url = tab.url;
    const api = await this.connect();
    if (api === null) return this.openSettings();
    try {
      if (typeof api === 'string') throw new Error(api);
      const saved = await api.save({ url, title: tab.title, tags: [] });
      this.problem = null;
      this.history.markSaved(url, saved.tags);
    } catch (error) {
      if (isOffline(error)) {
        this.problem = null;
        this.queue.add({ url, title: tab.title, tags: [] }, { failed: messageOf(error) });
        return;
      }
      this.problem = { page: pageKey(url), reason: messageOf(error) };
      this.pushChrome();
    }
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

  /** File > Saves Waiting: what is still to be delivered, to retry or drop. */
  showWaiting(): void {
    this.showOverlay({ mode: 'waiting', saves: this.history.pendingSaves() });
  }

  /** The system is back online: anything waiting may go now. */
  online(): void {
    void this.queue.flush();
  }

  retrySaves(id?: number): Promise<Delivery> {
    return this.queue.retry(id);
  }

  dropSave(id: number): void {
    this.queue.drop(id);
  }

  private showOverlay(state: OverlayState): void {
    this.overlayState = state;
    this.layout();
    this.window.contentView.addChildView(this.overlay);
    this.overlay.webContents.send(Channels.overlay.state, state);
    this.overlay.webContents.focus();
    this.releaseOmnibox();
  }

  closeOverlay(): void {
    if (!this.overlayState) return;
    this.overlayState = null;
    this.window.contentView.removeChildView(this.overlay);
    this.active()?.view.webContents.focus();
  }

  /** Which of this window's own views *contents* is, if any: IPC answers only those. */
  owns(contents: Electron.WebContents): 'chrome' | 'overlay' | 'history' | null {
    if (!this.window.isDestroyed() && contents === this.window.webContents) return 'chrome';
    if (contents === this.overlay.webContents) return 'overlay';
    if (this.tabs.some((t) => t.kind === 'internal' && t.view.webContents === contents)) return 'history';
    return null;
  }

  async saveFromSheet(tags: string[]): Promise<string | null> {
    const sheet = this.overlayState;
    const api = this.connection.api();
    if (sheet?.mode !== 'save' || !api) return 'Nothing to save.';
    // Saving a refused save again replaces its tags: the point is to fix them.
    const replace = sheet.pending?.refused === true;
    const queue = (failed?: string) => {
      this.queue.add({ url: sheet.url, title: sheet.title, tags }, { replace, failed });
      this.closeOverlay();
      return null;
    };
    if (sheet.offline) return queue();
    try {
      const saved = await api.save({ url: sheet.url, title: sheet.title, tags });
      if (replace && sheet.pending) this.queue.drop(sheet.pending.id); // fixed, and saved
      this.closeOverlay();
      this.problem = null;
      this.history.markSaved(sheet.url, saved.tags);
      return null;
    } catch (error) {
      return isOffline(error) ? queue(messageOf(error)) : messageOf(error);
    }
  }

  async removeTagFromSheet(tag: string): Promise<Bookmark | string> {
    const sheet = this.overlayState;
    const api = this.connection.api();
    if (sheet?.mode !== 'save' || !sheet.bookmark || !api) return 'Nothing to remove from.';
    try {
      const updated = await api.removeTag(sheet.bookmark.id, tag);
      this.overlayState = { ...sheet, bookmark: updated };
      this.history.markSaved(sheet.url, updated.tags);
      return updated;
    } catch (error) {
      if (isOffline(error)) return 'Can’t reach your bookmarks API, so tags can’t be removed until it’s back.';
      return messageOf(error);
    }
  }

  /**
   * Kept, and nothing sent for it. Saves waiting go to the API these settings name, at once:
   * a corrected address is the likeliest reason they were waiting (ADR 0017).
   */
  saveSettings(input: SettingsInput): void {
    this.settings.update(input);
    this.connection.reset();
    this.problem = null;
    this.closeOverlay();
    this.pushChrome();
    void this.queue.flush();
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

  // --- history (ADR 0016) ----------------------------------------------------------------

  /**
   * The history page, showing *view*: the one already open in this window if there is one,
   * else in this tab if it is blank, else in a new tab beside it.
   */
  showHistory(view: HistoryView = {}): void {
    const open = this.tabs.find((t) => t.kind === 'internal');
    if (open) {
      this.activate(open.id);
      open.view.webContents.send(Channels.history.view, view);
      return;
    }
    const tab = this.active();
    if (tab?.isBlank) this.open(historyUrl(view));
    else this.newTab(historyUrl(view), { index: tab ? this.tabs.indexOf(tab) + 1 : undefined });
  }

  /** History for This Site: the active page's host, or all of it for a page with none. */
  showSiteHistory(): void {
    const tab = this.active();
    const host = tab && isRecordable(tab.url) ? hostOf(tab.url) : '';
    this.showHistory(host ? { host } : {});
  }

  queryHistory(query: HistoryQuery): HistoryResult {
    return this.history.query({
      text: typeof query.text === 'string' ? query.text : undefined,
      host: typeof query.host === 'string' ? query.host : undefined,
      day: typeof query.day === 'string' ? query.day : undefined,
      before: Number.isFinite(query.before) ? Number(query.before) : undefined,
      limit: Number.isFinite(query.limit) ? Number(query.limit) : undefined,
    });
  }

  removeHistory(items: Array<{ pageId: number; day: string }>): void {
    this.history.remove(items.map((item) => ({ pageId: Number(item.pageId), day: String(item.day) })));
  }

  /** Delete browsing data: history over the range, cookies and cache for all time. */
  async clearBrowsingData(input: ClearInput): Promise<void> {
    const browse = this.environment.browse;
    if (input.history) this.history.clear(input.range);
    if (input.cookies) await browse.clearStorageData();
    if (input.cache) await browse.clearCache();
  }

  /** A page opened from the history page: in its own tab, or a new one. */
  openFromHistory(sender: Electron.WebContents, url: string, how: OpenDisposition): void {
    if (!isRecordable(url)) return;
    const from = this.tabs.find((t) => t.view.webContents === sender);
    if (!from) return;
    if (how === 'current') {
      from.load(url);
      this.focusPage(from);
    } else {
      this.newTab(url, { activate: how === 'foreground', index: this.tabs.indexOf(from) + 1 });
    }
  }

  private historyChanged(): void {
    this.pushChrome(); // a page saved here may be open in this window too
    // The Saves Waiting card follows deliveries as they happen, and closes once none wait.
    if (this.overlayState?.mode === 'waiting') {
      const saves = this.history.pendingSaves();
      if (saves.length) {
        this.overlayState = { mode: 'waiting', saves, update: true };
        this.overlay.webContents.send(Channels.overlay.state, this.overlayState);
      } else {
        this.closeOverlay();
      }
    }
    // The history pages follow, once a burst of changes (a page loading) has settled.
    if (this.historyTimer) clearTimeout(this.historyTimer);
    this.historyTimer = setTimeout(() => {
      for (const tab of this.tabs) {
        if (tab.kind === 'internal') tab.view.webContents.send(Channels.history.changed);
      }
    }, 150);
  }

  /**
   * The favicon kept with a visit, redrawn as a 32px PNG: the history page and the native
   * menu then show every one the same way, and a native menu cannot draw SVG or ICO. The
   * chrome draws it, since it already shows every favicon and is in a page it controls.
   */
  private keepFavicon(url: string, source: string): void {
    if (!isRecordable(url)) return;
    let drawn = this.favicons.get(source);
    if (!drawn) {
      drawn = this.rasterize(source);
      this.favicons.set(source, drawn);
      if (this.favicons.size > FAVICON_CACHE) this.favicons.delete(this.favicons.keys().next().value!);
    }
    void drawn.then((png) => {
      if (png) this.history.update(url, { favicon: png });
    });
  }

  private async rasterize(source: string): Promise<string | null> {
    if (this.window.isDestroyed()) return null;
    try {
      const png: unknown = await this.window.webContents.executeJavaScript(
        `(async () => {
          const image = new Image();
          image.src = ${JSON.stringify(source)};
          await image.decode();
          const canvas = document.createElement('canvas');
          canvas.width = canvas.height = 32;
          const scale = Math.min(32 / image.naturalWidth, 32 / image.naturalHeight) || 1;
          const w = image.naturalWidth * scale, h = image.naturalHeight * scale;
          canvas.getContext('2d').drawImage(image, (32 - w) / 2, (32 - h) / 2, w, h);
          return canvas.toDataURL('image/png');
        })()`,
      );
      return typeof png === 'string' && png.startsWith('data:image/png;base64,') ? png : null;
    } catch {
      return null; // an image the chrome cannot decode is no favicon, as in the tab strip
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
    if (this.disposed) return;
    if (this.sessionTimer) clearTimeout(this.sessionTimer);
    this.sessionTimer = setTimeout(() => this.saveSession(), 400);
  }

  saveSession(): void {
    if (this.sessionTimer) clearTimeout(this.sessionTimer);
    this.sessionTimer = null;
    if (this.disposed) return;
    const urls = this.tabs.map((t) => t.url);
    const active = Math.max(0, this.tabs.findIndex((t) => t.id === this.activeId));
    writeSession(this.paths.sessionFile, { urls, active });
  }

  /**
   * The window is gone, and its tabs with it. Nothing scheduled may run after this: a
   * session save that fired late read a destroyed tab and threw, and Electron's error
   * dialog then held the app open, so it never quit.
   */
  private dispose(): void {
    this.disposed = true;
    this.stopListening();
    if (this.historyTimer) clearTimeout(this.historyTimer);
    if (this.sessionTimer) clearTimeout(this.sessionTimer);
    for (const tab of this.tabs) tab.destroy();
    this.overlay.webContents.close();
  }
}

function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : String(error);
}
