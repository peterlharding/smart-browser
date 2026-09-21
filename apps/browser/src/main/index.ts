/**
 * The main process: one Browser per window, the menu, and the rules every web contents
 * lives under (ADR 0015).
 */

import { BrowserWindow, Menu, app, net, protocol, safeStorage, session } from 'electron';
import { join, normalize, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

import { Browser } from './browser';
import { History } from './history';
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
// registered only on the UI's session, so no web page can load it. The history page is
// smart://history/, its own origin, from the same files (ADR 0016).
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
let history: History;

function current(): Browser | null {
  const focused = BrowserWindow.getFocusedWindow();
  for (const browser of browsers) if (browser.window === focused) return browser;
  return browsers.values().next().value ?? null;
}

function openWindow(): Browser {
  const browser = new Browser(
    settings,
    {
      preload: paths.preload,
      sessionFile: paths.sessionFile(),
    },
    history,
  );
  browsers.add(browser);
  browser.window.on('closed', () => browsers.delete(browser));
  return browser;
}

// The History menu lists history, so it is rebuilt when history changes: at once, then at
// most once a second while pages load.
let menuBuiltAt = 0;
let menuTimer: NodeJS.Timeout | null = null;

function buildApplicationMenu(): void {
  menuTimer = null;
  menuBuiltAt = Date.now();
  Menu.setApplicationMenu(buildMenu(current, openWindow, history));
}

function rebuildMenuSoon(): void {
  if (menuTimer) return;
  menuTimer = setTimeout(buildApplicationMenu, Math.max(0, menuBuiltAt + 1000 - Date.now()));
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
  history = new History(join(app.getPath('userData'), 'history.db'));
  history.prune();
  history.onChange(rebuildMenuSoon);
  app.on('will-quit', () => history.close());

  protocol.handle('smart', (request) => {
    const url = new URL(request.url);
    // smart://history/ is the history page; its scripts and styles are the UI's own files.
    const path = url.host === 'history' && url.pathname === '/' ? '/history.html' : url.pathname;
    const file = normalize(join(paths.ui, decodeURIComponent(path)));
    if (!['ui', 'history'].includes(url.host) || !file.startsWith(paths.ui + sep)) {
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
  buildApplicationMenu();
  openWindow();

  app.on('activate', () => {
    if (browsers.size === 0) openWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
