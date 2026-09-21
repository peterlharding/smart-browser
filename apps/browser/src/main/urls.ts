/**
 * What kind of address a tab is showing, and when two addresses are the same page.
 *
 * Pure, so the rules are unit-tested rather than discovered by browsing.
 */

/** The browser's own pages, shown in tabs (ADR 0016). Only the history page, for now. */
export const HISTORY_URL = 'smart://history/';

/** The history page's address for *view*: what it shows is in its address, so it is restored. */
export function historyUrl(view: { text?: string; host?: string; day?: string; focus?: string; panel?: string } = {}): string {
  const params = new URLSearchParams();
  if (view.text) params.set('q', view.text);
  if (view.host) params.set('host', view.host);
  if (view.day) params.set('day', view.day);
  if (view.focus) params.set('focus', view.focus);
  if (view.panel) params.set('panel', view.panel);
  const query = params.toString();
  return query ? `${HISTORY_URL}?${query}` : HISTORY_URL;
}

/** A page on the web: what can be saved to the API. */
export function isWeb(url: string): boolean {
  return /^https?:/i.test(url);
}

/** What history records: web pages and local files, never the browser's own pages. */
export function isRecordable(url: string): boolean {
  return /^(https?|file):/i.test(url);
}

/** One of the browser's own pages, which a tab shows from its own session (ADR 0016). */
export function isInternal(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'smart:' && parsed.host === 'history';
  } catch {
    return false;
  }
}

/**
 * A page as the API tells pages apart: the fragment is a position within the page, not a
 * different one, unless it is a route starting `/` or `!` (ADR 0011). So `#top` after a
 * page loads is the same page, neither a new visit nor a different bookmark.
 */
export function pageKey(url: string): string {
  try {
    const parsed = new URL(url);
    if (parsed.hash && !/^#[/!]/.test(parsed.hash)) parsed.hash = '';
    return parsed.href;
  } catch {
    return url;
  }
}

/** The host, as "More from this site" means it; empty for a local file. */
export function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return '';
  }
}
