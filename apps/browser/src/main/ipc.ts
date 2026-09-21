/**
 * Every request the browser's UI can make of the main process, and nothing else (ADR 0015).
 *
 * Registered once for the app. Each request is answered only if it comes from a chrome or
 * an overlay of an open window, and by that window, so a second window's UI drives its own
 * tabs and a page can never reach these at all.
 */

import { ipcMain } from 'electron';

import { Channels, type SettingsInput } from '../shared/ipc';
import type { Browser } from './browser';

type Role = 'chrome' | 'overlay';

export function registerIpc(browsers: () => Iterable<Browser>): void {
  const handle = <A extends unknown[]>(role: Role, channel: string, handler: (b: Browser, ...args: A) => unknown) =>
    ipcMain.handle(channel, (event, ...args) => {
      for (const browser of browsers()) {
        if (browser.owns(event.sender) === role) return handler(browser, ...(args as A));
      }
      return undefined;
    });

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

  const o = Channels.overlay;
  handle('overlay', o.close, (b) => b.closeOverlay());
  handle('overlay', o.save, (b, tags: string[]) => b.saveFromSheet(Array.isArray(tags) ? tags.map(String) : []));
  handle('overlay', o.removeTag, (b, tag: string) => b.removeTagFromSheet(String(tag)));
  handle('overlay', o.saveSettings, (b, input: SettingsInput) => b.saveSettings(input));
  handle('overlay', o.testConnection, (b, input: SettingsInput) => b.testConnection(input));
}
