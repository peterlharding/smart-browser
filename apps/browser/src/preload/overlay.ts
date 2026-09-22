/**
 * The overlay's bridge: one function per request in OverlayApi (ADR 0015).
 */

import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron';

import { Channels, type OverlayApi, type OverlayState } from '../shared/ipc';

const o = Channels.overlay;

const api: OverlayApi = {
  close: () => ipcRenderer.invoke(o.close),
  save: (tags) => ipcRenderer.invoke(o.save, tags),
  removeTag: (tag) => ipcRenderer.invoke(o.removeTag, tag),
  saveSettings: (input) => ipcRenderer.invoke(o.saveSettings, input),
  testConnection: (input) => ipcRenderer.invoke(o.testConnection, input),
  retry: (id) => ipcRenderer.invoke(o.retry, id),
  drop: (id) => ipcRenderer.invoke(o.drop, id),
  onState(listener) {
    const handler = (_event: IpcRendererEvent, state: OverlayState) => listener(state);
    ipcRenderer.on(o.state, handler);
    return () => ipcRenderer.removeListener(o.state, handler);
  },
};

contextBridge.exposeInMainWorld('smart', api);
