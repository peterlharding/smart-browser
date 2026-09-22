/**
 * The application menu, which is where the keyboard shortcuts live: menu accelerators work
 * whichever view has focus, a web page included (ADR 0015). Chrome's shortcuts, plus ⌘⇧B
 * and ⌘⇧S from the extension.
 *
 * The History menu is built from history (ADR 0016), so the menu is rebuilt when history
 * changes: see index.ts.
 */

import { Menu, app, nativeImage, type MenuItemConstructorOptions, type NativeImage } from 'electron';

import type { Browser } from './browser';
import { dayOf, type History } from './history';

const RECENT_PAGES = 15;
const EARLIER_DAYS = 7;
const PAGES_PER_DAY = 30;
const LABEL_LENGTH = 60;

// Every item that does something has an id, so the end-to-end tests can trigger it: a
// native menu accelerator never passes through the page, so a test cannot press it.
export function buildMenu(
  current: () => Browser | null,
  newWindow: () => Browser,
  history: History,
): Menu {
  const on = (action: (browser: Browser) => void) => () => {
    const browser = current();
    if (browser) action(browser);
    else newWindow();
  };
  // History's items act even with no window open: a window opens, and then they act on it.
  const always = (action: (browser: Browser) => void) => () => action(current() ?? newWindow());
  const isMac = process.platform === 'darwin';

  const tabShortcuts: MenuItemConstructorOptions[] = Array.from({ length: 9 }, (_, i) => ({
    id: `tab-${i + 1}`,
    label: i === 8 ? 'Last Tab' : `Tab ${i + 1}`,
    accelerator: `CmdOrCtrl+${i + 1}`,
    click: on((b) => b.activateIndex(i === 8 ? -1 : i)),
  }));

  const template: MenuItemConstructorOptions[] = [
    ...(isMac
      ? [
          {
            label: app.name,
            submenu: [
              { role: 'about' },
              { type: 'separator' },
              { id: 'settings', label: 'Settings…', accelerator: 'Cmd+,', click: on((b) => b.openSettings()) },
              { type: 'separator' },
              { role: 'services' },
              { type: 'separator' },
              { role: 'hide' },
              { role: 'hideOthers' },
              { role: 'unhide' },
              { type: 'separator' },
              { role: 'quit' },
            ],
          } satisfies MenuItemConstructorOptions,
        ]
      : []),
    {
      label: 'File',
      submenu: [
        { id: 'new-tab', label: 'New Tab', accelerator: 'CmdOrCtrl+T', click: on((b) => b.newTab()) },
        { id: 'new-window', label: 'New Window', accelerator: 'CmdOrCtrl+N', click: newWindow },
        { id: 'open-location', label: 'Open Location…', accelerator: 'CmdOrCtrl+L', click: on((b) => b.focusLocation()) },
        { type: 'separator' },
        {
          id: 'save-sheet',
          label: 'Save Page with Tags…',
          accelerator: 'CmdOrCtrl+Shift+B',
          click: on((b) => void b.openSaveSheet()),
        },
        { id: 'quick-save', label: 'Quick Save', accelerator: 'CmdOrCtrl+Shift+S', click: on((b) => void b.quickSave()) },
        // Present only while saves wait for the API (ADR 0017).
        ...savesWaiting(history, on),
        { type: 'separator' },
        { id: 'close-tab', label: 'Close Tab', accelerator: 'CmdOrCtrl+W', click: on((b) => b.closeActive()) },
        ...(isMac ? [] : [{ type: 'separator' } as const, { id: 'settings', label: 'Settings', click: on((b) => b.openSettings()) }, { role: 'quit' } as const]),
      ],
    },
    { role: 'editMenu' },
    {
      label: 'View',
      submenu: [
        { id: 'reload', label: 'Reload This Page', accelerator: 'CmdOrCtrl+R', click: on((b) => b.reload()) },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
        { id: 'devtools', label: 'Developer Tools', accelerator: 'Alt+CmdOrCtrl+I', click: on((b) => b.toggleDevTools()) },
      ],
    },
    { label: 'History', submenu: historyMenu(history, always, isMac) },
    {
      label: 'Tab',
      submenu: [
        { id: 'next-tab', label: 'Next Tab', accelerator: 'Ctrl+Tab', click: on((b) => b.cycle(1)) },
        { id: 'previous-tab', label: 'Previous Tab', accelerator: 'Ctrl+Shift+Tab', click: on((b) => b.cycle(-1)) },
        { label: 'Next Tab ', accelerator: 'Alt+CmdOrCtrl+Right', click: on((b) => b.cycle(1)), visible: false },
        { label: 'Previous Tab ', accelerator: 'Alt+CmdOrCtrl+Left', click: on((b) => b.cycle(-1)), visible: false },
        { type: 'separator' },
        ...tabShortcuts,
      ],
    },
    { role: 'windowMenu' },
  ];
  return Menu.buildFromTemplate(template);
}

/**
 * Chrome's History menu and more (ADR 0016): the history page and its search, a site's
 * history, recently closed tabs, the pages visited last, and a submenu per earlier day.
 */
function historyMenu(
  history: History,
  always: (action: (browser: Browser) => void) => () => void,
  isMac: boolean,
): MenuItemConstructorOptions[] {
  const page = (id: string, url: string, title: string, favicon: string | null): MenuItemConstructorOptions => ({
    id,
    label: menuLabel(title || url, isMac),
    toolTip: url,
    icon: menuIcon(favicon),
    click: always((b) => b.open(url)),
  });

  const closed = history.closed();
  const recent = history.recent(RECENT_PAGES);
  const days = history.earlierDays(EARLIER_DAYS);

  return [
    { id: 'back', label: 'Back', accelerator: 'CmdOrCtrl+[', click: always((b) => b.back()) },
    { id: 'forward', label: 'Forward', accelerator: 'CmdOrCtrl+]', click: always((b) => b.forward()) },
    { type: 'separator' },
    {
      id: 'show-history',
      label: 'Show Full History',
      accelerator: isMac ? 'Cmd+Y' : 'Ctrl+H',
      click: always((b) => b.showHistory()),
    },
    {
      id: 'search-history',
      label: 'Search History…',
      accelerator: 'Alt+CmdOrCtrl+Y',
      click: always((b) => b.showHistory({ focus: 'search' })),
    },
    { id: 'site-history', label: 'History for This Site', click: always((b) => b.showSiteHistory()) },
    { type: 'separator' },
    {
      id: 'reopen-closed-tab',
      label: 'Reopen Closed Tab',
      accelerator: 'CmdOrCtrl+Shift+T',
      enabled: closed.length > 0,
      click: always((b) => b.reopenClosed()),
    },
    {
      id: 'recently-closed',
      label: 'Recently Closed',
      enabled: closed.length > 0,
      submenu: closed.map((tab, i) => ({
        id: `closed-${i}`,
        label: menuLabel(tab.title || tab.url, isMac),
        toolTip: tab.url,
        icon: menuIcon(tab.favicon),
        click: always((b) => b.reopenClosed(tab.id)),
      })),
    },
    ...(recent.length
      ? ([
          { type: 'separator' },
          { label: 'Recently Visited', enabled: false },
          ...recent.map((p, i) => page(`recent-${i}`, p.url, p.title, p.favicon)),
        ] satisfies MenuItemConstructorOptions[])
      : []),
    ...(days.length
      ? ([
          { type: 'separator' },
          ...days.map((day, i) => ({
            id: `day-${i}`,
            label: dayLabel(day),
            submenu: [
              ...history
                .query({ day, limit: PAGES_PER_DAY })
                .entries.map((e, j) => page(`day-${i}-page-${j}`, e.url, e.title, e.favicon)),
              { type: 'separator' },
              {
                id: `day-${i}-all`,
                label: 'Show Full History for This Day',
                click: always((b) => b.showHistory({ day })),
              },
            ] satisfies MenuItemConstructorOptions[],
          })),
        ] satisfies MenuItemConstructorOptions[])
      : []),
    { type: 'separator' },
    {
      id: 'delete-browsing-data',
      label: 'Delete Browsing Data…',
      accelerator: 'CmdOrCtrl+Shift+Backspace',
      click: always((b) => b.showHistory({ panel: 'clear' })),
    },
  ];
}

/** A page's title as a menu item: shortened, and on Windows and Linux `&` is not a mnemonic. */
export function menuLabel(title: string, isMac: boolean): string {
  const single = title.replace(/\s+/g, ' ').trim();
  const short = single.length > LABEL_LENGTH ? `${single.slice(0, LABEL_LENGTH - 1).trimEnd()}…` : single;
  return isMac ? short : short.replace(/&/g, '&&');
}

let genericIcon: NativeImage | undefined;

/**
 * A favicon kept by history is a 32px PNG (see Browser.keepFavicon), drawn here at 16
 * points. A page with none gets a globe, as Chrome shows it.
 */
function menuIcon(favicon: string | null): NativeImage | undefined {
  if (favicon?.startsWith('data:image/png;base64,')) {
    const image = nativeImage.createFromBuffer(Buffer.from(favicon.slice(22), 'base64'), { scaleFactor: 2 });
    if (!image.isEmpty()) return image;
  }
  if (process.platform !== 'darwin') return undefined;
  // Drawn at 32 pixels and marked 2x, so it is sharp on a Retina display, as favicons are.
  genericIcon ??= nativeImage.createFromBuffer(
    nativeImage.createFromNamedImage('NSNetwork').resize({ width: 32, height: 32 }).toPNG(),
    { scaleFactor: 2 },
  );
  return genericIcon;
}

/** "Yesterday", or the weekday and date, as Safari names its earlier days. */
function dayLabel(day: string): string {
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (day === dayOf(yesterday.getTime())) return 'Yesterday';
  const [year, month, date] = day.split('-').map(Number);
  return new Intl.DateTimeFormat(app.getLocale(), { weekday: 'long', day: 'numeric', month: 'long' }).format(
    new Date(year!, month! - 1, date!),
  );
}

function savesWaiting(
  history: History,
  on: (action: (browser: Browser) => void) => () => void,
): MenuItemConstructorOptions[] {
  const count = history.pendingSaves().length;
  if (!count) return [];
  return [{ id: 'saves-waiting', label: `Saves Waiting (${count})…`, click: on((b) => b.showWaiting()) }];
}
