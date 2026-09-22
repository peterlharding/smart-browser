/**
 * Every message between the main process and the browser's own UI (ADR 0015).
 *
 * The preloads expose one function per entry here and nothing else, so what a renderer can
 * ask of the main process is exactly this list, and changing a shape fails to compile on
 * both sides at once.
 */

import type { components } from './api-types';

export type Bookmark = components['schemas']['BookmarkOut'];
export type TagCount = components['schemas']['TagOut'];
export type Health = components['schemas']['Health'];

/** The contract this build speaks. `/api/v1/health` must report the same (ADR 0005). */
export const API_CONTRACT_VERSION = 1;

export type SearchEngine = 'duckduckgo' | 'google' | 'bing';

export interface TabState {
  id: number;
  url: string;
  title: string;
  favicon: string | null;
  loading: boolean;
}

/**
 * What the toolbar's save button says about the active page. Only what this browser knows:
 * it never asks the API while you browse (ADR 0016), so `savable` claims nothing about
 * whether the page is saved, only that it can be.
 */
export type SavedState =
  | { kind: 'not-web' }
  | { kind: 'unconfigured' }
  | { kind: 'unavailable'; reason: string }
  | { kind: 'savable' }
  | { kind: 'saved'; tags: string[] }
  /** Saved here while the API was away, not yet delivered (ADR 0017). */
  | { kind: 'waiting'; tags: string[] }
  /** Saved here, and refused by the API when it came back. */
  | { kind: 'refused'; reason: string };

/** A save made while the API was away, waiting to be delivered (ADR 0017). */
export interface PendingSave {
  id: number;
  url: string;
  title: string;
  tags: string[];
  /** When you first saved it, in milliseconds. */
  savedAt: number;
  /** Moves on with every change, so a delivery never removes tags queued during it. */
  version: number;
  attempts: number;
  lastError: string | null;
  /** The API answered no: it waits for you, not for the API. */
  refused: boolean;
}

export interface ChromeState {
  tabs: TabState[];
  activeId: number | null;
  canGoBack: boolean;
  canGoForward: boolean;
  saved: SavedState;
  /** Set once to focus the omnibox: a new tab, or ⌘L. Increments so repeats register. */
  focusOmnibox: number;
}

export interface SaveSheet {
  mode: 'save';
  url: string;
  title: string;
  bookmark: Bookmark | null;
  vocabulary: TagCount[];
  error: string | null;
  /** The API could not be reached: saving queues, and the tags shown are what is known here. */
  offline: boolean;
  /** Offline, the tags this browser knows the page was saved with, or null if it knows none. */
  known: string[] | null;
  /** A save of this page still waiting, or refused. */
  pending: PendingSave | null;
}

/** How a delivery of waiting saves went. */
export type Delivery = 'nothing' | 'delivered' | 'offline' | 'blocked';

/** File > Saves Waiting: everything still to be delivered (ADR 0017). */
export interface WaitingView {
  mode: 'waiting';
  saves: PendingSave[];
  /** The open card's list, updated as saves go: the same card, not a fresh one. */
  update?: boolean;
}

export interface SettingsView {
  mode: 'settings';
  apiUrl: string;
  hasToken: boolean;
  searchEngine: SearchEngine;
  tokenStorage: 'keychain' | 'unavailable';
}

export type OverlayState = SaveSheet | SettingsView | WaitingView;

export interface SettingsInput {
  apiUrl: string;
  /** Omitted keeps the stored token; an empty string removes it. */
  token?: string;
  searchEngine: SearchEngine;
}

export type ConnectionReport =
  | { ok: true; version: string; contract: number; schema: string | null; compatible: boolean }
  | { ok: false; reason: string };

/** One row of the history page: a page's visits on one day, shown at the latest (ADR 0016). */
export interface HistoryEntry {
  pageId: number;
  /** The local day, "2026-09-22". */
  day: string;
  url: string;
  title: string;
  host: string;
  /** A 32px PNG data: URL, drawn at 16 points. */
  favicon: string | null;
  /** The latest visit that day, in milliseconds. */
  at: number;
}

export interface HistoryQuery {
  /** Words each starting a word of the title or address. */
  text?: string;
  /** Only this host: "More from this site". */
  host?: string;
  /** Only this day. */
  day?: string;
  /** Continue after the row with this `at`. */
  before?: number;
  limit?: number;
}

export interface HistoryResult {
  entries: HistoryEntry[];
  more: boolean;
}

/** What the history page is asked to show: from the menu, or its own address. */
export interface HistoryView {
  text?: string;
  host?: string;
  day?: string;
  /** Put the caret in the search box: Search History, ⌥⌘Y. */
  focus?: 'search';
  /** Open the Delete browsing data panel. */
  panel?: 'clear';
}

export type ClearRange = 'hour' | 'day' | 'week' | 'month' | 'all';

export interface ClearInput {
  range: ClearRange;
  history: boolean;
  /** Cookies and site data, for all time: Electron clears them by origin, not by date. */
  cookies: boolean;
  /** Cached images and files, for all time, for the same reason. */
  cache: boolean;
}

/** Where a page opened from history goes: this tab, or a new one behind or in front. */
export type OpenDisposition = 'current' | 'background' | 'foreground';

/** Requests from the chrome: tab strip, toolbar and omnibox. */
export interface ChromeApi {
  newTab(): Promise<void>;
  closeTab(id: number): Promise<void>;
  activateTab(id: number): Promise<void>;
  moveTab(id: number, index: number): Promise<void>;
  navigate(input: string): Promise<void>;
  back(): Promise<void>;
  forward(): Promise<void>;
  reload(): Promise<void>;
  stop(): Promise<void>;
  openSaveSheet(): Promise<void>;
  openSettings(): Promise<void>;
  onState(listener: (state: ChromeState) => void): () => void;
  /** Focus has moved to a page or the overlay: they share the window, so no DOM blur fires. */
  onBlur(listener: () => void): () => void;
  /** The system is back online: saves waiting may go now (ADR 0017). */
  online(): Promise<void>;
}

/** Requests from the overlay: the save sheet and settings. */
export interface OverlayApi {
  close(): Promise<void>;
  save(tags: string[]): Promise<string | null>;
  removeTag(tag: string): Promise<Bookmark | string>;
  saveSettings(input: SettingsInput): Promise<void>;
  testConnection(input: SettingsInput): Promise<ConnectionReport>;
  /** Try a waiting or refused save again now: one, or all of them. */
  retry(id?: number): Promise<Delivery>;
  /** Give up on a waiting or refused save. */
  drop(id: number): Promise<void>;
  onState(listener: (state: OverlayState) => void): () => void;
}

/** Requests from the history page, a tab of the browser's own (ADR 0016). */
export interface HistoryApi {
  query(query: HistoryQuery): Promise<HistoryResult>;
  remove(items: Array<{ pageId: number; day: string }>): Promise<void>;
  clear(input: ClearInput): Promise<void>;
  open(url: string, how: OpenDisposition): Promise<void>;
  /** History changed: a visit, a deletion. The page asks again. */
  onChanged(listener: () => void): () => void;
  /** The menu asked this open page to show something: a search, a site, a day. */
  onView(listener: (view: HistoryView) => void): () => void;
}

/** Channel names. Handlers and preloads both use these, so a typo is a compile error. */
export const Channels = {
  chrome: {
    newTab: 'chrome:new-tab',
    closeTab: 'chrome:close-tab',
    activateTab: 'chrome:activate-tab',
    moveTab: 'chrome:move-tab',
    navigate: 'chrome:navigate',
    back: 'chrome:back',
    forward: 'chrome:forward',
    reload: 'chrome:reload',
    stop: 'chrome:stop',
    openSaveSheet: 'chrome:open-save-sheet',
    openSettings: 'chrome:open-settings',
    state: 'chrome:state',
    blur: 'chrome:blur',
    online: 'chrome:online',
  },
  overlay: {
    close: 'overlay:close',
    save: 'overlay:save',
    removeTag: 'overlay:remove-tag',
    saveSettings: 'overlay:save-settings',
    testConnection: 'overlay:test-connection',
    retry: 'overlay:retry',
    drop: 'overlay:drop',
    state: 'overlay:state',
  },
  history: {
    query: 'history:query',
    remove: 'history:remove',
    clear: 'history:clear',
    open: 'history:open',
    changed: 'history:changed',
    view: 'history:view',
  },
} as const;
