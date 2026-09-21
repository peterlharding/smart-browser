/**
 * Service worker: quick save, context menu, and the badge.
 *
 * The popup handles tagging. This handles the case where you want the page kept and do
 * not want to think about it -- which is how the existing corpus ended up 80.8% untagged,
 * so it is deliberately the *second* shortcut rather than the first.
 */

import { BookmarksApi } from './lib/api.js';
import { contextMenuTarget } from './lib/quicksave.js';
import { loadSettings } from './lib/settings.js';

const CONTEXT_MENU_ID = 'smart-browser-save';

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: CONTEXT_MENU_ID,
    title: 'Save to Smart-Browser',
    contexts: ['page', 'link'],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== CONTEXT_MENU_ID) return;
  quickSave(contextMenuTarget(info, tab));
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== 'quick-save') return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab) quickSave({ url: tab.url, title: tab.title, tabId: tab.id });
});

async function quickSave({ url, title, tabId }) {
  if (!url) return;
  const settings = await loadSettings();
  const api = new BookmarksApi(settings);

  try {
    const bookmark = await api.save({ url, title });
    // No tags, so say so: an untagged save is the thing worth noticing, not celebrating.
    await flashBadge(tabId, bookmark.tags.length ? '✓' : '+', bookmark.tags.length ? '#2e7d32' : '#b26a00');
  } catch (error) {
    await flashBadge(tabId, '!', '#c62828');
    console.error('[smart-browser] quick save failed:', error.message, error.detail ?? '');
  }
}

async function flashBadge(tabId, text, colour) {
  const target = tabId ? { tabId } : {};
  await chrome.action.setBadgeBackgroundColor({ ...target, color: colour });
  await chrome.action.setBadgeText({ ...target, text });
  setTimeout(() => chrome.action.setBadgeText({ ...target, text: '' }), 2500);
}
