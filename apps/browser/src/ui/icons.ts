/** 16px stroke icons, drawn for this UI; `currentColor` so they follow the theme. */

const icon = (body: string) =>
  `<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

export const icons = {
  back: icon('<path d="M13 8H3.5M7.5 4 3.5 8l4 4"/>'),
  forward: icon('<path d="M3 8h9.5M8.5 4l4 4-4 4"/>'),
  reload: icon('<path d="M13.2 8a5.2 5.2 0 1 1-1.5-3.7"/><path d="M13.2 2.6v2.9h-2.9"/>'),
  stop: icon('<path d="m4 4 8 8M12 4l-8 8"/>'),
  close: icon('<path d="m4.5 4.5 7 7M11.5 4.5l-7 7"/>'),
  plus: icon('<path d="M8 3v10M3 8h10"/>'),
  bookmark: icon('<path d="M4 2.5h8v11L8 10.6 4 13.5z"/>'),
  bookmarkFilled:
    '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5h8v11L8 10.6 4 13.5z" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
  warning: icon('<path d="M8 2.2 14.2 13H1.8z"/><path d="M8 6.4v3.1M8 11.3v.1"/>'),
  settings: icon(
    '<path d="M2.5 4h11M2.5 8h11M2.5 12h11"/><circle cx="10.5" cy="4" r="1.7" fill="var(--toolbar)"/><circle cx="5.5" cy="8" r="1.7" fill="var(--toolbar)"/><circle cx="9" cy="12" r="1.7" fill="var(--toolbar)"/>',
  ),
  clock: icon('<circle cx="8" cy="8" r="6"/><path d="M8 4.6V8l2.3 1.5"/>'),
  search: icon('<circle cx="7" cy="7" r="4.3"/><path d="m10.2 10.2 3.3 3.3"/>'),
  more: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="3.5" r="1.3" fill="currentColor"/><circle cx="8" cy="8" r="1.3" fill="currentColor"/><circle cx="8" cy="12.5" r="1.3" fill="currentColor"/></svg>',
  trash: icon('<path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5"/>'),
  globe: icon('<circle cx="8" cy="8" r="5.8"/><path d="M2.2 8h11.6M8 2.2c1.7 1.8 2.5 3.7 2.5 5.8S9.7 12 8 13.8C6.3 12 5.5 10.1 5.5 8S6.3 4 8 2.2z"/>'),
};
