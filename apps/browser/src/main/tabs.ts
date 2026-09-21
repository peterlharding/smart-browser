/**
 * One tab: a sandboxed `WebContentsView` in the browsing session, and what the tab strip
 * shows of it (ADR 0015).
 */

import { Menu, WebContentsView, clipboard, type Session } from 'electron';

import type { TabState } from '../shared/ipc';

const MAX_FAVICON_BYTES = 256 * 1024;

export interface TabEvents {
  /** Anything the tab strip or toolbar shows has changed. */
  changed(tab: Tab): void;
  /** The page's URL changed: the saved-state indicator needs a fresh answer. */
  navigated(tab: Tab): void;
  /** The page asked for a new window; it becomes a tab instead. */
  openTab(url: string, opener: Tab): void;
}

let nextId = 1;

export class Tab {
  readonly id = nextId++;
  readonly view: WebContentsView;
  title = 'New Tab';
  /** What load() was last asked for: getURL() is empty until that navigation commits. */
  private requested = 'about:blank';
  favicon: string | null = null;

  constructor(
    session: Session,
    private readonly events: TabEvents,
  ) {
    this.view = new WebContentsView({
      webPreferences: {
        session,
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
        webSecurity: true,
        // No preload: a page gets nothing from the browser but what any page gets.
      },
    });
    this.view.setBackgroundColor('#ffffff');
    const contents = this.view.webContents;

    // window.open and target=_blank become tabs in the tab model, never unmanaged windows.
    contents.setWindowOpenHandler(({ url }) => {
      this.events.openTab(url, this);
      return { action: 'deny' };
    });

    contents.on('page-title-updated', (_event, title) => {
      this.title = this.titleOf(title);
      this.events.changed(this);
    });
    contents.on('page-favicon-updated', (_event, urls) => {
      void this.loadFavicon(urls[0]);
    });
    contents.on('did-start-loading', () => this.events.changed(this));
    contents.on('did-stop-loading', () => this.events.changed(this));
    contents.on('did-navigate', () => {
      this.favicon = null;
      this.title = this.titleOf(contents.getTitle());
      this.events.changed(this);
      this.events.navigated(this);
    });
    contents.on('did-navigate-in-page', (_event, _url, isMainFrame) => {
      if (!isMainFrame) return;
      this.events.changed(this);
      this.events.navigated(this);
    });
    contents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
      // -3 is an aborted load: a new navigation replaced this one, which is not a failure.
      if (!isMainFrame || code === -3) return;
      this.title = `${description} — ${url}`;
      this.events.changed(this);
    });
    contents.on('context-menu', (_event, params) => this.contextMenu(params));
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
    this.requested = url;
    void this.view.webContents.loadURL(url).catch(() => {
      // Failures arrive as did-fail-load, which is where they are shown.
    });
  }

  destroy(): void {
    this.view.webContents.close();
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
      const response = await this.view.webContents.session.fetch(url);
      const type = response.headers.get('content-type') ?? '';
      if (!response.ok || !type.startsWith('image/')) return;
      const bytes = Buffer.from(await response.arrayBuffer());
      if (bytes.length > MAX_FAVICON_BYTES || this.url !== page) return;
      this.favicon = `data:${type.split(';')[0]};base64,${bytes.toString('base64')}`;
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
        enabled: contents.navigationHistory.canGoBack(),
        click: () => contents.navigationHistory.goBack(),
      },
      {
        label: 'Forward',
        enabled: contents.navigationHistory.canGoForward(),
        click: () => contents.navigationHistory.goForward(),
      },
      { label: 'Reload', click: () => contents.reload() },
      { type: 'separator' },
      { label: 'Inspect Element', click: () => contents.inspectElement(params.x, params.y) },
    );
    Menu.buildFromTemplate(items).popup();
  }
}
