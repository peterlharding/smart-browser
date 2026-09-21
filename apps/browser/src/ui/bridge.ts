/**
 * The preload's bridge, typed for the page that has it: the chrome gets ChromeApi, the
 * overlay OverlayApi, and neither can call the other's at compile time.
 */

import type { ChromeApi, OverlayApi } from '../shared/ipc';

const bridge = (window as unknown as { smart: unknown }).smart;

export const chromeApi = () => bridge as ChromeApi;
export const overlayApi = () => bridge as OverlayApi;
