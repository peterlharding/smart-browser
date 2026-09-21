/**
 * What a context-menu save should save. Pure, so `node --test` can check it.
 *
 * The title sent with a save is the title as seen (ADR 0010), and it outranks the title
 * the crawler fetches. That makes a wrong title worse than none: on a link, the tab's
 * title belongs to the page doing the linking, not the page linked to, so a link save
 * sends no title and lets the crawler supply one.
 */
export function contextMenuTarget(info, tab) {
  if (info.linkUrl) return { url: info.linkUrl, title: undefined, tabId: tab?.id };
  return { url: info.pageUrl || tab?.url, title: tab?.title, tabId: tab?.id };
}
