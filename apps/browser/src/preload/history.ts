/**
 * The history page's bridge: one function per request in HistoryApi (ADR 0016). The page
 * runs in the UI's session, so no web page ever has this.
 */

import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron';

import { Channels, type HistoryApi, type HistoryView } from '../shared/ipc';

const h = Channels.history;

const api: HistoryApi = {
  query: (query) => ipcRenderer.invoke(h.query, query),
  remove: (items) => ipcRenderer.invoke(h.remove, items),
  clear: (input) => ipcRenderer.invoke(h.clear, input),
  open: (url, how) => ipcRenderer.invoke(h.open, url, how),
  onChanged(listener) {
    const handler = () => listener();
    ipcRenderer.on(h.changed, handler);
    return () => ipcRenderer.removeListener(h.changed, handler);
  },
  onView(listener) {
    const handler = (_event: IpcRendererEvent, view: HistoryView) => listener(view);
    ipcRenderer.on(h.view, handler);
    return () => ipcRenderer.removeListener(h.view, handler);
  },
};

contextBridge.exposeInMainWorld('smart', api);
