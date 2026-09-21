# 0016 - Browsing history is local; the API is for what you choose to keep

- **Date:** 2026-09-22
- **Status:** Accepted
- **Builds on:** [ADR 0015](0015-electron-shell.md) (the shell)
- **Supersedes, in part:** ADR 0015's saved-state indicator, which asked the API about every page

## Context

Using the first slice for a day, the browser talked to the bookmarks API far more than it needed to.
Every page loaded, and every tab switched to, asked `GET /bookmarks/lookup` whether it was saved, and every launch asked `/health`.
The answers only fed the toolbar's indicator, and a cache in front of them (`lookups.ts`) reduced the traffic without changing what it was for.

That is the wrong relationship.
The API holds what you choose to keep, and it has no business hearing about every page you look at.
Meanwhile the browser keeps no record of where you have been at all, so it has nothing like Chrome's History menu, history page, or "reopen closed tab".

## Decision

### The API is contacted only when you act

- **The API is called only when you ask for something:** opening the save sheet (`⌘⇧B`, or clicking the toolbar button), a quick save (`⌘⇧S`), removing a tag in the sheet, or testing the connection in Settings.
  Nothing is sent on navigation, on tab switches, on saving Settings or at launch.
- **The contract check (ADR 0005) happens on the first of those actions in a session**, and again after Settings change, rather than at launch.
- **The toolbar's indicator shows what this browser knows**, not what the API would say.
  A page saved or looked up from this browser (through the sheet or a quick save) is remembered locally with its tags, and shows as saved.
  Any other page shows a neutral "save" button, which claims nothing about whether it is saved: a page saved from the extension is found when you open the sheet, which asks the API and remembers the answer.
- `lookups.ts` and its per-page cache go: with no background lookups there is nothing for them to save.

### Browsing history is kept locally

**In SQLite, in the profile directory** (`history.db`), through Node's built-in `node:sqlite`, which Electron 44 bundles (Node 24.21, SQLite 3.53 with FTS5, checked on this Mac).
No native module to rebuild for Electron, and full-text search of titles and addresses is one query.
It never leaves the machine.

**What is recorded:**

- A visit whenever a tab's main frame commits a navigation, and when a page changes its address other than by the fragment (`pushState`), as Chrome does.
  Each visit keeps its time, address, title (updated as the page sets it) and the page's favicon.
- Not recorded: blank tabs, the browser's own pages, and loads that failed.
- **Kept for 90 days**, as Chrome keeps it, pruned at launch.

**The History menu** starts from Chrome's on the Mac and goes further, so most of what the history page does can be reached without opening it:

- Back and Forward, as now.
- **Show Full History** (`⌘Y`), and **Search History...** (`⌥⌘Y`), which opens the history page with its search box focused.
- **History for This Site**: the history page narrowed to the current page's site, the menu's form of the page's "More from this site".
- **Recently Closed**: a submenu of the last 10 tabs closed, each reopened with its own back and forward history, and **Reopen Closed Tab** (`⇧⌘T`), which reopens the most recent.
- **The most recently visited pages**, about 15, with their favicons, each opening in the current tab.
- **Earlier days**, as Safari has them: a submenu per day for the past week ("Yesterday", "Monday 21 September", ...), each listing that day's pages, newest first, up to about 30, and a last item opening the history page at that day.
- **Delete Browsing Data...** (`⇧⌘⌫`, Chrome's shortcut), opening the history page's panel for it.

The menu is native, so it is rebuilt from `history.db` when history changes, and at most once a second while you browse.
Its favicons come from the stored data URLs, as `nativeImage`s at 16 points.
Items for a page show its title, shortened to about 60 characters, with the address as the tooltip, and a page with no title shows its address.

**The history page** is a tab, as Chrome's is, and follows its layout:

- A search box across the top, searching titles and addresses.
- Visits grouped by day under headings like "Today - Tuesday, 22 September 2026", newest first, each row a checkbox, the time, the favicon, the title and the site, loading more as you scroll.
- Each row's menu offers **More from this site** (the list narrowed to that site) and **Delete from history**; ticking rows offers **Delete** for all of them.
- **Delete browsing data** on the side opens a panel to clear browsing history, cookies and site data, and cached files, over the last hour, day, week, four weeks or all time.
  Cookies and cache are the browsing session's, through Electron's session API.
- Not built: Chrome's "By group" view and "Tabs from other devices", which have nothing to draw on here.

**The history page runs in the browser's own session, not the browsing session**, with its own preload exposing only history queries and deletions, as the save sheet's does.
A web page can no more reach it, or the history database, than it can reach Settings.

### Where each piece lives

- `history.ts` in the main process owns the database: recording visits, searching, deleting, pruning, recently closed tabs and the locally known saves.
- The tab model gains a second kind of tab, an internal page, which is a view in the browser's session showing `smart://history/`, with a preload of its own.
  A history tab is restored on the next launch like any other.

## Options not taken

- **Keep the background lookups, cached harder.**
  It makes the traffic smaller, not absent, and the API still hears about every site you visit.
- **Show nothing in the indicator until the sheet is opened.**
  Simpler, but a page you saved a minute ago would look unsaved.
  What this browser saved itself is known without asking anyone.
- **Store history in the bookmarks API.**
  It would make history available to other devices, which nothing needs yet, and it is exactly the traffic this decision removes.
- **A JSON file for history.**
  Fine at first, and slow to search and awkward to prune at the size a browser's history reaches in weeks.
- **`better-sqlite3`.**
  A native module that must be rebuilt for each Electron version, for what Node already ships.
- **A History menu only as long as Chrome's.**
  Chrome leaves searching, a site's history and earlier days to its history page.
  Each of those is one menu item here, and a menu is where a Mac user looks first.
- **Search inside the menu itself.**
  A native menu cannot hold a text field that filters as you type without a custom view, which Electron does not offer, so search opens the page.
- **The history page in the overlay rather than a tab.**
  The overlay is for things you glance at and dismiss; history is somewhere you go, search and come back to, as it is in Chrome.

## Consequences

- The browser sends nothing to the API while you browse.
  The API's log shows saves, sheets opened and settings tested, and nothing else.
- A page saved elsewhere, from the extension say, shows the neutral button until the sheet is opened on it.
- The profile directory gains `history.db`, which holds every address visited for 90 days.
  It is the user's own machine and profile, and "Delete browsing data" empties it of visits and closed tabs.
  What this browser knows was saved stays: it records what you chose to keep, not where you went.
- The end-to-end tests check the traffic: browsing, switching tabs and launching send nothing to the API.

## Implementation notes

Where building it refined the decision above.

- **A visit is to a page, not an address with a fragment.**
  History keys pages as the API does (`pageKey`, ADR 0011), so `article.html#section` is the same page as `article.html`, and a route fragment (`#/settings`) is not.
- **Favicons are redrawn as 32-pixel PNGs by the chrome.**
  A native menu cannot draw SVG or ICO, and many favicons are one or the other.
  The chrome already shows every favicon from inside a page the app controls, so the main process has it draw each one onto a canvas once, and history keeps the PNG.
- **A favicon fetched after the tab has moved on is still kept.**
  A page left before its icon arrived was still visited, and would otherwise be listed without one.
- **Chromium announces a page's icons only when they change.**
  The second of two pages with the same icon announces nothing, so the tab keeps the icon it had when the new page announces none.
  This was a bug in the tab strip too, from the first slice, and is fixed there as well.
- **The history page is `smart://history/`, its own origin**, served from the UI's files, in the UI's session, with a bridge of its own.
  A tab switches between a web view and this view as it goes from one kind of page to the other.
  A page opened from the history page takes its tab, and Back from that page's first entry returns to the history page, as it would in Chrome.
- **What the history page shows is in its address** (`?q=`, `?host=`, `?day=`), so a restored tab shows it again.
  Show Full History reuses the history page already open in the window, as a menu item that means "go there" should.
- **Cookies and cached files are deleted for all time, whatever the range.**
  Electron clears them by origin, not by date, and the panel says so when the range is shorter.
- **The recently closed list is the application's, not a window's**, as Chrome's is, and closing a window's last tab closes the window instead: the next window reopens its tabs from the session.
