/**
 * What typing in the omnibox means: a URL is visited, anything else is searched (ADR 0015).
 *
 * Pure, so the rules are unit-tested rather than discovered by typing.
 */

import type { SearchEngine } from '../shared/ipc';

export const SEARCH_ENGINES: Record<SearchEngine, { name: string; template: string }> = {
  duckduckgo: { name: 'DuckDuckGo', template: 'https://duckduckgo.com/?q=%s' },
  google: { name: 'Google', template: 'https://www.google.com/search?q=%s' },
  bing: { name: 'Bing', template: 'https://www.bing.com/search?q=%s' },
};

// Schemes a tab may be sent to from the omnibox. Anything else (javascript:, data:, the
// internal schemes) is searched for rather than opened.
const OPENABLE = new Set(['http:', 'https:', 'about:', 'file:']);

// A host and optional port with no scheme: example.com, docs.python.org/3/, localhost:8085,
// 127.0.0.1, [::1]:8080. A dot needs a letter-only suffix of two or more, so `node.js` is
// a host and `3.14` a search.
const HOSTLIKE =
  /^(localhost|\d{1,3}(\.\d{1,3}){3}|\[[0-9a-f:.]+\]|([a-z0-9-]+\.)+[a-z]{2,63})(:\d{1,5})?([/?#].*)?$/i;
const LOCAL = /^(localhost|127\.\d+\.\d+\.\d+|\[::1\])(:|\/|$)/i;

export function resolveInput(input: string, engine: SearchEngine): string | null {
  const text = input.trim();
  if (!text) return null;

  if (!/\s/.test(text)) {
    if (HOSTLIKE.test(text)) {
      return `${LOCAL.test(text) ? 'http' : 'https'}://${text}`;
    }
    const scheme = /^([a-z][a-z0-9+.-]*):/i.exec(text)?.[1];
    if (scheme) {
      try {
        const url = new URL(text);
        if (OPENABLE.has(url.protocol)) return url.href;
      } catch {
        // Not a URL after all: search for it.
      }
    }
  }
  return SEARCH_ENGINES[engine].template.replace('%s', encodeURIComponent(text));
}

/** What the omnibox shows for a page: the URL, except for the blank new-tab page. */
export function displayUrl(url: string): string {
  return url === 'about:blank' ? '' : url;
}
