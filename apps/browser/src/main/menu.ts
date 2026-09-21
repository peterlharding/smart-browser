/**
 * The application menu, which is where the keyboard shortcuts live: menu accelerators work
 * whichever view has focus, a web page included (ADR 0015). Chrome's shortcuts, plus ⌘⇧B
 * and ⌘⇧S from the extension.
 */

import { Menu, app, type MenuItemConstructorOptions } from 'electron';

import type { Browser } from './browser';

// Every item that does something has an id, so the end-to-end tests can trigger it: a
// native menu accelerator never passes through the page, so a test cannot press it.
export function buildMenu(current: () => Browser | null, newWindow: () => void): Menu {
  const on = (action: (browser: Browser) => void) => () => {
    const browser = current();
    if (browser) action(browser);
    else newWindow();
  };
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
    {
      label: 'History',
      submenu: [
        { id: 'back', label: 'Back', accelerator: 'CmdOrCtrl+[', click: on((b) => b.back()) },
        { id: 'forward', label: 'Forward', accelerator: 'CmdOrCtrl+]', click: on((b) => b.forward()) },
      ],
    },
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
