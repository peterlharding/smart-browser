/**
 * One tab: a sandboxed `WebContentsView`, what the tab strip shows of it (ADR 0015), and
 * what history hears from it (ADR 0016).
 */

import { Menu, WebContentsView, clipboard, nativeTheme, session as sessions, type Session } from 'electron';
import { join } from 'node:path';

import type { TabState } from '../shared/ipc';
import { isInternal, isRecordable, pageKey } from './urls';

const MAX_FAVICON_BYTES = 256 * 1024;

export interface TabEvents {
  /** Anything the tab strip or toolbar shows has changed. */
  changed(tab: Tab): void;
  /** The page's URL changed: the session and the toolbar follow it. */
  navigated(tab: Tab): void;
  /** The page asked for a new window; it becomes a tab instead. */
  openTab(url: string, opener: Tab): void;
  /** A page history should record committed: a load, or an in-page move to another page. */
  visited(tab: Tab, url: string): void;
  /** The page set its title, which history keeps with the visit. */
  titled(tab: Tab): void;
  /**
   * The favicon of *page*, fetched: history keeps it even if the tab has moved on, since a
   * page left quickly was still visited.
   */
  favicon(tab: Tab, page: string, favicon: string): void;
  /** The tab changed kind, so its view is a new one: *old* is about to be closed. */
  replaced(tab: Tab, old: WebContentsView): void;
}

export interface TabEnvironment {
  /** The browsing session, `persist:browse`, where every web page runs. */
  browse: Session;
  /** The directory of the built preloads, for the browser's own pages. */
  preload: string;
}

/** Restoring a tab's back and forward history, as a recently closed tab reopens. */
export interface Navigation {
  entries: Array<{ url: string; title: string; pageState?: string }>;
  index: number;
}

let nextId = 1;

/**
 * A tab shows web pages, or one of the browser's own pages (ADR 0016), and never both in
 * one view: a web page runs sandboxed in the browsing session with no preload, and the
 * browser's own page in the UI's session with its bridge. Going from one to the other
 * swaps the view; the tab, its place and its id stay.
 */
export class Tab {
  readonly id = nextId++;
  view: WebContentsView;
  kind: 'web' | 'internal';
  title = 'New Tab';
  /** The title the page itself set, if any: what history keeps, never one made from the URL. */
  pageTitle = '';
  favicon: string | null = null;
  /** The browser's own page this tab showed before a page opened from it: where Back goes. */
  private returnTo: string | null = null;
  /** What load() was last asked for: getURL() is empty until that navigation commits. */
  private requested: string;
  /** The last page recorded as visited, so a fragment or a replaceState is not a new visit. */
  private lastVisit: string | null = null;
  /** The favicon before this navigation, and whether the page has announced its own since. */
  private carried: string | null = null;
  private iconAnnounced = false;

  constructor(
    private readonly env: TabEnvironment,
    private readonly events: TabEvents,
    url = 'about:blank',
    navigation?: Navigation,
  ) {
    this.kind = isInternal(url) ? 'internal' : 'web';
    this.view = this.createView(this.kind);
    this.requested = url;
    if (navigation) {
      void this.view.webContents.navigationHistory.restore(navigation).catch(() => {
        // A history that no longer restores still leaves the tab, at its page.
        this.load(url);
      });
    } else {
      this.load(url);
    }
  }

  get url(): string {
    return this.view.webContents.getURL() || this.requested;
  }

  /** A new tab page: blank, and not on its way anywhere else. */
  get isBlank(): boolean {
    return this.url === 'about:blank';
  }

  state(): TabState {
    return {
      id: this.id,
      url: this.url,
      title: this.title,
      favicon: this.favicon,
      loading: this.view.webContents.isLoading(),
    };
  }

  load(url: string): void {
    const kind = isInternal(url) ? 'internal' : 'web';
    if (kind !== this.kind) this.replaceView(kind);
    this.requested = url;
    void this.view.webContents.loadURL(url).catch(() => {
      // Failures arrive as did-fail-load, which is where they are shown.
    });
  }

  get canGoBack(): boolean {
    return this.view.webContents.navigationHistory.canGoBack() || this.returnTo !== null;
  }

  get canGoForward(): boolean {
    return this.view.webContents.navigationHistory.canGoForward();
  }

  /** Back through the page's history, and from its first page to the history page it came from. */
  goBack(): void {
    const history = this.view.webContents.navigationHistory;
    if (history.canGoBack()) history.goBack();
    else if (this.returnTo) this.load(this.returnTo);
  }

  goForward(): void {
    this.view.webContents.navigationHistory.goForward();
  }

  /** What reopening this tab needs: its back and forward history. */
  navigation(): Navigation {
    const history = this.view.webContents.navigationHistory;
    return { entries: history.getAllEntries(), index: history.getActiveIndex() };
  }

  destroy(): void {
    this.view.webContents.close();
  }

  private replaceView(kind: 'web' | 'internal'): void {
    const old = this.view;
    this.returnTo = this.kind === 'internal' ? this.url : null;
    this.kind = kind;
    this.view = this.createView(kind);
    this.title = 'New Tab';
    this.pageTitle = '';
    this.favicon = null;
    this.lastVisit = null;
    this.events.replaced(this, old);
    old.webContents.close();
  }

  private createView(kind: 'web' | 'internal'): WebContentsView {
    const view =
      kind === 'web'
        ? new WebContentsView({
            webPreferences: {
              session: this.env.browse,
              sandbox: true,
              contextIsolation: true,
              nodeIntegration: false,
              webSecurity: true,
              // No preload: a page gets nothing from the browser but what any page gets.
            },
          })
        : new WebContentsView({
            webPreferences: {
              // The UI's session, the only one where smart:// is served, with the history
              // page's bridge and nothing else (ADR 0016).
              session: sessions.defaultSession,
              preload: join(this.env.preload, 'history.cjs'),
              sandbox: true,
              contextIsolation: true,
              nodeIntegration: false,
            },
          });
    if (kind === 'web') view.setBackgroundColor('#ffffff');
    // The history page's own background (--page in theme.css), so it opens without a flash.
    else view.setBackgroundColor(nativeTheme.shouldUseDarkColors ? '#1c1f24' : '#f3f4f6');
    this.wire(view.webContents, kind);
    return view;
  }

  private wire(contents: Electron.WebContents, kind: 'web' | 'internal'): void {
    // Events from a view this tab has since replaced are about a page it no longer shows.
    const live = () => this.view.webContents === contents;

    if (kind === 'internal') lockToAppFiles(contents);
    else {
      // window.open and target=_blank become tabs in the tab model, never unmanaged windows.
      contents.setWindowOpenHandler(({ url }) => {
        this.events.openTab(url, this);
        return { action: 'deny' };
      });
    }

    contents.on('page-title-updated', (_event, title, explicitSet) => {
      if (!live()) return;
      this.title = this.titleOf(title);
      if (explicitSet) this.pageTitle = title;
      this.events.changed(this);
      this.events.titled(this);
    });
    contents.on('page-favicon-updated', (_event, urls) => {
      if (!live()) return;
      this.iconAnnounced = true;
      void this.loadFavicon(urls[0]);
    });
    contents.on('did-start-loading', () => live() && this.events.changed(this));
    contents.on('did-stop-loading', () => {
      if (!live()) return;
      // Chromium announces a page's icons only when they differ from the last page's, so a
      // page with the same icon as the one before it announces nothing: it keeps that icon.
      if (!this.iconAnnounced && this.carried && !this.favicon) {
        this.favicon = this.carried;
        this.events.favicon(this, this.url, this.carried);
      }
      this.carried = null;
      this.events.changed(this);
    });
    // Only a load that commits is a visit: a failed one fires did-fail-load and not this.
    contents.on('did-navigate', (_event, url, code) => {
      if (!live()) return;
      this.carried = this.favicon ?? this.carried;
      this.iconAnnounced = false;
      this.favicon = null;
      this.pageTitle = '';
      this.title = this.titleOf(contents.getTitle());
      this.events.changed(this);
      this.events.navigated(this);
      if (kind === 'web' && isRecordable(url) && (code > 0 || url.startsWith('file:'))) this.visit(url);
    });
    contents.on('did-navigate-in-page', (_event, url, isMainFrame) => {
      if (!isMainFrame || !live()) return;
      this.events.changed(this);
      this.events.navigated(this);
      // pushState to another page is a visit, as Chrome counts it; a fragment is not.
      if (kind === 'web' && isRecordable(url) && pageKey(url) !== this.lastVisit) this.visit(url);
    });
    contents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
      // -3 is an aborted load: a new navigation replaced this one, which is not a failure.
      if (!isMainFrame || code === -3 || !live()) return;
      this.title = `${description} — ${url}`;
      this.events.changed(this);
    });
    contents.on('context-menu', (_event, params) => this.contextMenu(params));
  }

  private visit(url: string): void {
    this.lastVisit = pageKey(url);
    this.events.visited(this, url);
  }

  /**
   * What the tab strip shows. A page with no <title> gets Chromium's own name for it, its
   * host and path, as Chrome shows it; a blank page is what Chrome calls a New Tab.
   */
  private titleOf(reported: string): string {
    const url = this.url;
    if (url === 'about:blank') return 'New Tab';
    return reported || url;
  }

  /**
   * Fetched by the main process through the tab's own session and passed on as a data:
   * URL, so the browser's UI never touches the network (ADR 0015).
   */
  private async loadFavicon(url: string | undefined): Promise<void> {
    if (!url || !/^(https?|data):/i.test(url)) return;
    const page = this.url;
    try {
      // A data: icon, as the history page's is, is decoded here: the session's fetch does
      // not answer one.
      const response = /^data:/i.test(url) ? await fetch(url) : await this.view.webContents.session.fetch(url);
      const type = response.headers.get('content-type') ?? '';
      if (!response.ok || !type.startsWith('image/')) return;
      const bytes = Buffer.from(await response.arrayBuffer());
      if (bytes.length > MAX_FAVICON_BYTES) return;
      const favicon = `data:${type.split(';')[0]};base64,${bytes.toString('base64')}`;
      this.events.favicon(this, page, favicon);
      if (this.url !== page) return;
      this.favicon = favicon;
      this.events.changed(this);
    } catch {
      // No favicon is a fine answer.
    }
  }

  private contextMenu(params: Electron.ContextMenuParams): void {
    const contents = this.view.webContents;
    const items: Electron.MenuItemConstructorOptions[] = [];
    if (params.linkURL) {
      items.push(
        { label: 'Open Link in New Tab', click: () => this.events.openTab(params.linkURL, this) },
        { label: 'Copy Link Address', click: () => clipboard.writeText(params.linkURL) },
        { type: 'separator' },
      );
    }
    if (params.isEditable) {
      items.push({ role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { type: 'separator' });
    } else if (params.selectionText) {
      items.push({ role: 'copy' }, { type: 'separator' });
    }
    items.push(
      {
        label: 'Back',
        enabled: this.canGoBack,
        click: () => this.goBack(),
      },
      {
        label: 'Forward',
        enabled: this.canGoForward,
        click: () => this.goForward(),
      },
      { label: 'Reload', click: () => contents.reload() },
      { type: 'separator' },
      { label: 'Inspect Element', click: () => contents.inspectElement(params.x, params.y) },
    );
    Menu.buildFromTemplate(items).popup();
  }
}

/** The browser's own pages show the app's files and nothing else (ADR 0015). */
export function lockToAppFiles(contents: Electron.WebContents): void {
  contents.on('will-navigate', (event) => event.preventDefault());
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
}
