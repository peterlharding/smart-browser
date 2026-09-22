/**
 * The chrome's bridge: one function per request in ChromeApi, and never ipcRenderer
 * itself (ADR 0015).
 */

import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron';

import { Channels, type ChromeApi, type ChromeState } from '../shared/ipc';

const c = Channels.chrome;

const api: ChromeApi = {
  newTab: () => ipcRenderer.invoke(c.newTab),
  closeTab: (id) => ipcRenderer.invoke(c.closeTab, id),
  activateTab: (id) => ipcRenderer.invoke(c.activateTab, id),
  moveTab: (id, index) => ipcRenderer.invoke(c.moveTab, id, index),
  navigate: (input) => ipcRenderer.invoke(c.navigate, input),
  back: () => ipcRenderer.invoke(c.back),
  forward: () => ipcRenderer.invoke(c.forward),
  reload: () => ipcRenderer.invoke(c.reload),
  stop: () => ipcRenderer.invoke(c.stop),
  openSaveSheet: () => ipcRenderer.invoke(c.openSaveSheet),
  openSettings: () => ipcRenderer.invoke(c.openSettings),
  online: () => ipcRenderer.invoke(c.online),
  onState(listener) {
    const handler = (_event: IpcRendererEvent, state: ChromeState) => listener(state);
    ipcRenderer.on(c.state, handler);
    return () => ipcRenderer.removeListener(c.state, handler);
  },
  onBlur(listener) {
    const handler = () => listener();
    ipcRenderer.on(c.blur, handler);
    return () => ipcRenderer.removeListener(c.blur, handler);
  },
};

contextBridge.exposeInMainWorld('smart', api);
