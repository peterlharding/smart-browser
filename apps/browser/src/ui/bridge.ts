/**
 * The preload's bridge, typed for the page that has it: the chrome gets ChromeApi, the
 * overlay OverlayApi, the history page HistoryApi, and none can call another's at compile
 * time.
 */

import type { ChromeApi, HistoryApi, OverlayApi } from '../shared/ipc';

const bridge = (window as unknown as { smart: unknown }).smart;

export const chromeApi = () => bridge as ChromeApi;
export const overlayApi = () => bridge as OverlayApi;
export const historyApi = () => bridge as HistoryApi;
