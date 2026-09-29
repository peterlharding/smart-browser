/**
 * The main process: one Browser per window, the menu, and the rules every web contents
 * lives under (ADR 0015).
 */

import { BrowserWindow, Menu, app, autoUpdater, net, powerMonitor, protocol, safeStorage, session } from 'electron';
import { join, normalize, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

import { Browser } from './browser';
import { Connection } from './connection';
import { History } from './history';
import { registerIpc } from './ipc';
import { buildMenu } from './menu';
import { SaveQueue } from './queue';
import { SettingsStore, type Secrets } from './settings';
import { Updates, type Updater } from './updates';

app.setName('Smart-Browser');
// The profile follows the build (ADR 0018): the installed app browses in "Smart-Browser",
// a build run from the repo in "Smart-Browser Dev", so experiments never touch real
// history, and a development build's history.db migration never moves the installed
// app's profile past what it knows. The tests name a throwaway profile of their own.
// Must be set before the app is ready.
if (process.env.SMART_BROWSER_USER_DATA) {
  app.setPath('userData', process.env.SMART_BROWSER_USER_DATA);
} else if (!app.isPackaged) {
  app.setPath('userData', join(app.getPath('appData'), 'Smart-Browser Dev'));
}

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
let connection: Connection;
let queue: SaveQueue;
let updates: Updates;

/** The browser's GitHub repository: whose latest release update.electronjs.org serves. */
const REPO = 'peterlharding/smart-browser';

// Electron's own updater, behind the narrow surface updates.ts uses (ADR 0019).
const updater: Updater = {
  setFeedURL: (feed) => autoUpdater.setFeedURL(feed),
  checkForUpdates: () => autoUpdater.checkForUpdates(),
  quitAndInstall: () => autoUpdater.quitAndInstall(),
  onDownloaded: (listener) =>
    autoUpdater.on('update-downloaded', (_event, _notes, name) => listener(name)),
  onError: (listener) => autoUpdater.on('error', listener),
};

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
    connection,
    queue,
    updates,
  );
  browsers.add(browser);
  browser.window.on('closed', () => browsers.delete(browser));
  return browser;
}

// The History menu lists history, so it is rebuilt when history changes: at once, then at
// most once a second while pages load.
let menuBuiltAt = 0;
let menuTimer: NodeJS.Timeout | null = null;
let quitting = false;

function buildApplicationMenu(): void {
  menuTimer = null;
  menuBuiltAt = Date.now();
  Menu.setApplicationMenu(buildMenu(current, openWindow, history, updates));
}

function rebuildMenuSoon(): void {
  if (menuTimer || quitting) return;
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
  // Saves made while the API was away (ADR 0017): one queue and one connection for the app.
  connection = new Connection(settings);
  queue = new SaveQueue(history, connection);
  queue.start();
  powerMonitor.on('resume', () => void queue.flush()); // the Mac woke: the API may be back

  // Updating itself (ADR 0019). A build run from the repo cannot replace itself, and the
  // tests must reach no service, so both are off rather than merely quiet.
  updates = new Updates(
    updater,
    {
      repo: REPO,
      version: app.getVersion(),
      platform: process.platform,
      arch: process.arch,
      packaged: app.isPackaged,
      underTest: Boolean(process.env.SMART_BROWSER_NO_UPDATE),
      automatic: settings.autoUpdate,
    },
    () => {
      rebuildMenuSoon();
      for (const browser of browsers) browser.updatesChanged();
    },
    (message) => console.log(`[updates] ${message}`),
  );
  updates.start();
  // Nothing that reads history.db may run once it is closed: a menu rebuild due a moment
  // after a page's favicon arrived threw, and Electron's error dialog held the app open.
  app.on('will-quit', () => {
    quitting = true;
    updates.stop();
    if (menuTimer) clearTimeout(menuTimer);
    menuTimer = null;
    queue.stop();
    history.close();
  });

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
