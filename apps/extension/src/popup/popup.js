/**
 * The save sheet.
 *
 * This is the whole point of the extension, and eventually of the browser: the moment of
 * saving is the only moment you actually know what a page is about. The existing corpus
 * averages 1.44 tags on the 19% of bookmarks that have any, because tagging happened
 * later, by hand, somewhere else. Here it costs a keystroke.
 *
 * Two rules keep this honest:
 *
 *   Opening the popup performs a *lookup*, never a save -- otherwise merely glancing at
 *   the shortcut would create rows.
 *
 *   Saving is always a single POST /bookmarks, which is an upsert. This client never
 *   decides whether a page is new; the server does, atomically, in one request.
 */

import { BookmarksApi, NotConfigured } from '../lib/api.js';
import { loadSettings } from '../lib/settings.js';
import { activeFragment, completeFragment, parseTags, suggest } from '../lib/tags.js';

const el = {
  state: document.getElementById('state'),
  title: document.getElementById('title'),
  site: document.getElementById('site'),
  current: document.getElementById('current'),
  currentTags: document.getElementById('current-tags'),
  input: document.getElementById('tags'),
  suggestions: document.getElementById('suggestions'),
  save: document.getElementById('save'),
  options: document.getElementById('options'),
  message: document.getElementById('message'),
};

let api = null;
let tab = null;
let bookmark = null;
let vocabulary = [];

init();

async function init() {
  el.options.addEventListener('click', (event) => {
    event.preventDefault();
    chrome.runtime.openOptionsPage();
  });
  el.save.addEventListener('click', onSave);
  el.input.addEventListener('input', renderSuggestions);
  el.input.addEventListener('keydown', onKeyDown);

  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url) return fail('No active tab.');

  el.title.textContent = tab.title || tab.url;
  el.title.title = tab.url;
  el.site.textContent = siteOf(tab.url);

  const settings = await loadSettings();
  api = new BookmarksApi(settings);
  if (!api.configured) {
    setState('error', 'Not configured');
    return fail('Set the API address and token in Options first.');
  }

  // Deliberately concurrent, and deliberately tolerant: a failed vocabulary fetch costs
  // autocomplete, not the ability to save.
  const [found, tags] = await Promise.all([
    api.lookup(tab.url).catch((error) => { fail(error.message); return undefined; }),
    api.tags({ minCount: 1 }).catch(() => []),
  ]);
  if (found === undefined) return;

  vocabulary = tags ?? [];
  bookmark = found;
  render();
  el.input.focus();
}

function render() {
  if (bookmark) {
    setState('saved', bookmark.tags.length ? 'Saved' : 'Saved · untagged');
    el.save.textContent = 'Add tags';
    renderCurrentTags();
  } else {
    setState('new', 'Not saved yet');
    el.save.textContent = 'Save';
    el.current.hidden = true;
  }
  renderSuggestions();
}

function renderCurrentTags() {
  el.current.hidden = bookmark.tags.length === 0;
  el.currentTags.replaceChildren(
    ...bookmark.tags.map((name) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.innerHTML = `${escapeHtml(name)}<span class="remove" aria-hidden="true">×</span>`;
      button.title = `Remove "${name}"`;
      button.addEventListener('click', () => onRemoveTag(name));
      const li = document.createElement('li');
      li.append(button);
      return li;
    }),
  );
}

function renderSuggestions() {
  const typed = parseTags(el.input.value);
  const exclude = [...(bookmark?.tags ?? []), ...typed];
  const matches = suggest(vocabulary, activeFragment(el.input.value), { exclude });

  el.suggestions.replaceChildren(
    ...matches.map((entry) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.innerHTML = `${escapeHtml(entry.name)}<span class="count">${entry.count}</span>`;
      button.addEventListener('click', () => {
        el.input.value = completeFragment(el.input.value, entry.name);
        el.input.focus();
        renderSuggestions();
      });
      const li = document.createElement('li');
      li.append(button);
      return li;
    }),
  );
}

function onKeyDown(event) {
  if (event.key === 'Enter') {
    event.preventDefault();
    onSave();
  }
  // Tab accepts the top suggestion, the way an omnibox would.
  if (event.key === 'Tab') {
    const [first] = suggest(vocabulary, activeFragment(el.input.value), {
      limit: 1,
      exclude: [...(bookmark?.tags ?? []), ...parseTags(el.input.value)],
    });
    if (first) {
      event.preventDefault();
      el.input.value = completeFragment(el.input.value, first.name);
      renderSuggestions();
    }
  }
}

async function onSave() {
  const tags = parseTags(el.input.value);

  el.save.disabled = true;
  hideMessage();

  try {
    // One call, whether or not the page is already saved. POST /bookmarks is an upsert:
    // it returns 201 for a new bookmark and 200 for one that already existed, merging the
    // tags in either case. Branching here on what the lookup found would be the client
    // deciding something the server has already decided, and would go wrong the moment
    // the page is saved from somewhere else between the lookup and the save.
    bookmark = await api.save({ url: tab.url, title: tab.title || '', tags });
    el.input.value = '';
    render();
    window.close();
  } catch (error) {
    fail(error instanceof NotConfigured ? `${error.message} Open Options.` : error.message);
  } finally {
    el.save.disabled = false;
  }
}

async function onRemoveTag(name) {
  try {
    bookmark = await api.removeTag(bookmark.id, name);
    render();
  } catch (error) {
    fail(error.message);
  }
}

function setState(kind, text) {
  el.state.className = `state state--${kind}`;
  el.state.textContent = text;
}

function fail(text) {
  el.message.textContent = text;
  el.message.className = 'message message--error';
  el.message.hidden = false;
}

function hideMessage() {
  el.message.hidden = true;
}

function siteOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}
