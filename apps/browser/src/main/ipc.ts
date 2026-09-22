/**
 * Every request the browser's UI can make of the main process, and nothing else (ADR 0015).
 *
 * Registered once for the app. Each request is answered only if it comes from a chrome or
 * an overlay of an open window, and by that window, so a second window's UI drives its own
 * tabs and a page can never reach these at all.
 */

import { ipcMain } from 'electron';

import { Channels, type ClearInput, type ClearRange, type HistoryQuery, type OpenDisposition, type SettingsInput } from '../shared/ipc';
import type { Browser } from './browser';

type Role = 'chrome' | 'overlay' | 'history';

const RANGES: readonly ClearRange[] = ['hour', 'day', 'week', 'month', 'all'];
const DISPOSITIONS: readonly OpenDisposition[] = ['current', 'background', 'foreground'];

export function registerIpc(browsers: () => Iterable<Browser>): void {
  // The sender is passed first to what needs to know which view asked: the history page
  // is a tab, and "open here" means its own tab.
  const handleFrom = <A extends unknown[]>(
    role: Role,
    channel: string,
    handler: (b: Browser, sender: Electron.WebContents, ...args: A) => unknown,
  ) =>
    ipcMain.handle(channel, (event, ...args) => {
      for (const browser of browsers()) {
        if (browser.owns(event.sender) === role) return handler(browser, event.sender, ...(args as A));
      }
      return undefined;
    });
  const handle = <A extends unknown[]>(role: Role, channel: string, handler: (b: Browser, ...args: A) => unknown) =>
    handleFrom<A>(role, channel, (b, _sender, ...args) => handler(b, ...args));

  const c = Channels.chrome;
  handle('chrome', c.newTab, (b) => void b.newTab());
  handle('chrome', c.closeTab, (b, id: number) => b.close(Number(id)));
  handle('chrome', c.activateTab, (b, id: number) => b.activate(Number(id)));
  handle('chrome', c.moveTab, (b, id: number, index: number) => b.move(Number(id), Number(index)));
  handle('chrome', c.navigate, (b, input: string) => b.navigate(String(input)));
  handle('chrome', c.back, (b) => b.back());
  handle('chrome', c.forward, (b) => b.forward());
  handle('chrome', c.reload, (b) => b.reload());
  handle('chrome', c.stop, (b) => b.stop());
  handle('chrome', c.openSaveSheet, (b) => b.openSaveSheet());
  handle('chrome', c.openSettings, (b) => b.openSettings());
  handle('chrome', c.online, (b) => b.online());

  const o = Channels.overlay;
  handle('overlay', o.close, (b) => b.closeOverlay());
  handle('overlay', o.save, (b, tags: string[]) => b.saveFromSheet(Array.isArray(tags) ? tags.map(String) : []));
  handle('overlay', o.removeTag, (b, tag: string) => b.removeTagFromSheet(String(tag)));
  handle('overlay', o.saveSettings, (b, input: SettingsInput) => b.saveSettings(input));
  handle('overlay', o.testConnection, (b, input: SettingsInput) => b.testConnection(input));
  handle('overlay', o.retry, (b, id?: number) => b.retrySaves(id === undefined || id === null ? undefined : Number(id)));
  handle('overlay', o.drop, (b, id: number) => b.dropSave(Number(id)));

  // The history page is a tab: its requests are answered by the window it is in.
  const h = Channels.history;
  handle('history', h.query, (b, query: HistoryQuery) => b.queryHistory(query ?? {}));
  handle('history', h.remove, (b, items: Array<{ pageId: number; day: string }>) =>
    b.removeHistory(Array.isArray(items) ? items : []),
  );
  handle('history', h.clear, (b, input: ClearInput) =>
    b.clearBrowsingData({
      range: RANGES.includes(input?.range) ? input.range : 'hour',
      history: input?.history === true,
      cookies: input?.cookies === true,
      cache: input?.cache === true,
    }),
  );
  handleFrom('history', h.open, (b, sender, url: string, how: OpenDisposition) =>
    b.openFromHistory(sender, String(url), DISPOSITIONS.includes(how) ? how : 'current'),
  );
}
