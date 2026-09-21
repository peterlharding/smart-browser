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

/** Whether the active tab's page is in your library. */
export type SavedState =
  | { kind: 'unknown' }
  | { kind: 'not-web' }
  | { kind: 'unconfigured' }
  | { kind: 'unavailable'; reason: string }
  | { kind: 'unsaved' }
  | { kind: 'saved'; tags: string[] };

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
}

export interface SettingsView {
  mode: 'settings';
  apiUrl: string;
  hasToken: boolean;
  searchEngine: SearchEngine;
  tokenStorage: 'keychain' | 'unavailable';
}

export type OverlayState = SaveSheet | SettingsView;

export interface SettingsInput {
  apiUrl: string;
  /** Omitted keeps the stored token; an empty string removes it. */
  token?: string;
  searchEngine: SearchEngine;
}

export type ConnectionReport =
  | { ok: true; version: string; contract: number; schema: string | null; compatible: boolean }
  | { ok: false; reason: string };

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
}

/** Requests from the overlay: the save sheet and settings. */
export interface OverlayApi {
  close(): Promise<void>;
  save(tags: string[]): Promise<string | null>;
  removeTag(tag: string): Promise<Bookmark | string>;
  saveSettings(input: SettingsInput): Promise<void>;
  testConnection(input: SettingsInput): Promise<ConnectionReport>;
  onState(listener: (state: OverlayState) => void): () => void;
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
  },
  overlay: {
    close: 'overlay:close',
    save: 'overlay:save',
    removeTag: 'overlay:remove-tag',
    saveSettings: 'overlay:save-settings',
    testConnection: 'overlay:test-connection',
    state: 'overlay:state',
  },
} as const;
