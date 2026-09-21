/**
 * The main process: one Browser per window, the menu, and the rules every web contents
 * lives under (ADR 0015).
 */

import { BrowserWindow, Menu, app, net, protocol, safeStorage, session } from 'electron';
import { join, normalize, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

import { Browser } from './browser';
import { registerIpc } from './ipc';
import { buildMenu } from './menu';
import { SettingsStore, type Secrets } from './settings';

// A separate profile, for development and for the end-to-end tests, so neither touches
// the one you browse with. Must be set before the app is ready.
if (process.env.SMART_BROWSER_USER_DATA) {
  app.setPath('userData', process.env.SMART_BROWSER_USER_DATA);
}
app.setName('Smart-Browser');

// The browser's own UI is served from smart://ui/, a private scheme, rather than file://:
// it gives the UI a real origin, so its CSP can say "this app and nothing else", and it is
// registered only on the UI's session, so no web page can load it.
protocol.registerSchemesAsPrivileged([
  { scheme: 'smart', privileges: { standard: true, secure: true } },
]);

const out = join(__dirname, '..');
const paths = {
  ui: join(out, 'ui'),
  preload: join(out, 'preload'),
  sessionFile: () => join(app.getPath('userData'), 'session.json'),
};

const browsers = new Set<Browser>();
let settings: SettingsStore;

function current(): Browser | null {
  const focused = BrowserWindow.getFocusedWindow();
  for (const browser of browsers) if (browser.window === focused) return browser;
  return browsers.values().next().value ?? null;
}

function openWindow(): void {
  const browser = new Browser(settings, {
    preload: paths.preload,
    sessionFile: paths.sessionFile(),
  });
  browsers.add(browser);
  browser.window.on('closed', () => browsers.delete(browser));
}

const secrets: Secrets = {
  available: () => safeStorage.isEncryptionAvailable(),
  // Linux has several possible stores, and "none available" is only useful with which.
  describe: () =>
    process.platform === 'linux' ? `backend: ${safeStorage.getSelectedStorageBackend()}` : process.platform,
  encrypt: (text) => safeStorage.encryptString(text),
  decrypt: (data) => safeStorage.decryptString(data),
};

// Every web contents the app creates, whatever it is: no <webview>, no permission a page
// has not been given a UI to ask for.
app.on('web-contents-created', (_event, contents) => {
  contents.on('will-attach-webview', (event) => event.preventDefault());
});

void app.whenReady().then(() => {
  settings = new SettingsStore(join(app.getPath('userData'), 'settings.json'), secrets);

  protocol.handle('smart', (request) => {
    const url = new URL(request.url);
    const file = normalize(join(paths.ui, decodeURIComponent(url.pathname)));
    if (url.host !== 'ui' || !file.startsWith(paths.ui + sep)) {
      return new Response('Not found', { status: 404 });
    }
    return net.fetch(pathToFileURL(file).toString());
  });

  // Camera, microphone, location, notifications and the rest are denied until the browser
  // has a way to ask you (ADR 0015).
  const browse = session.fromPartition('persist:browse');
  browse.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  browse.setPermissionCheckHandler(() => false);

  registerIpc(() => browsers);
  Menu.setApplicationMenu(buildMenu(current, openWindow));
  openWindow();

  app.on('activate', () => {
    if (browsers.size === 0) openWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
