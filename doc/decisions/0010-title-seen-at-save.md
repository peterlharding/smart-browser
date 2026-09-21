# 0010 - The title you saw is kept apart from the title you chose

- **Date:** 2026-09-21
- **Status:** Accepted

## Context

A bookmark has three candidate titles, and today the schema has room for two of them.

1. **The title you typed.**
   Yours alone, and it should win over everything.
   `user_bookmark.title_override` exists for this.
2. **The title the crawler fetched.**
   The page's `<title>` as a robot sees it, shared by everyone who saved the URL.
   `bookmark.title` exists for this, and M3 is about to start filling it.
3. **The title the browser showed when you saved.**
   What was in the tab at the moment of saving.
   Nothing exists for this, so the extension writes it into `title_override`.

The third one is squatting in the first one's column, and three things go wrong because of it.

- **The crawled title never appears for anything saved from the extension.**
  `title_override` wins by design, and the extension fills it on every save.
  M3 would fetch and store titles that no extension save ever displays.
- **"You typed this" stops meaning anything.**
  An override is supposed to record a decision.
  Once the browser writes it on every save, a title you corrected is indistinguishable from one Chrome happened to show.
- **Saving a link from the context menu records the wrong title.**
  The background worker sends the link's URL with the *current tab's* title, so the saved page carries the title of the page that linked to it.

The browser's title is not a lesser copy of the crawled one, either.
For a large class of pages it is the only title there will ever be.

- **Pages behind a login.**
  Gmail, private GitHub repositories, internal dashboards.
  The crawler has no session, so it gets a login page, and its title is "Sign in".
- **Pages the crawler cannot reach at all.**
  `localhost`, intranet hosts, anything on a VPN.
- **Single-page apps.**
  The static HTML is a shell whose `<title>` is the framework's default, and the real title arrives from JavaScript the crawler does not run.

The predecessor's corpus shows what losing titles costs: 96% of its 9,472 bookmarks have no title at all (audit, 2026-09-20).

## Options

### A. The extension stops sending the tab title

The crawled title becomes the only non-typed title.

Lost because it throws away the one title that is right for every page in the list above.
Until the crawl finishes every save is also titled by its URL, and a failed crawl leaves it that way permanently.

### B. The tab title fills `bookmark.title` when that is empty

One column, and the crawler overwrites it or not.

Lost because `bookmark` is shared (ADR 0001).
A tab title is private in a way a URL is not: `Inbox (3) - someone@example.com`, `Invoice 1043 for a named customer`.
Writing it to the shared row publishes one person's view of a page to everyone who saves that URL, and the first person to save a page would set its title for everybody.

### C. Leave it as it is

Lost for the three reasons in the context: M3's titles would be invisible, overrides would mean nothing, and the context-menu bug would stay.

### D. A per-save column for the title as seen

`user_bookmark.saved_title` holds what the client saw.
`title_override` goes back to meaning only what you typed.

This is the decision.

## Decision

**`user_bookmark.saved_title`** is new, and holds the title the client saw when it saved.
It is per save, like `saved_from`, so it is never shared and never leaks.

**Display precedence is override, then saved, then crawled:**

```text
title = title_override ?? saved_title ?? bookmark.title
```

What you saw beats what a robot saw.
For a login-walled page the robot saw "Sign in", and for a single-page app it saw the framework's default, so a crawled title that outranked the saved one would be wrong for exactly the pages where the saved one is the only good title.
The crawled title still matters.
It titles saves that arrive with no title (API calls, imports, link saves), and it stays on `bookmark` for search and for M4, whatever the display shows.

**`POST /bookmarks` `title` means the title as seen**, and writes `saved_title`.
**`PATCH /bookmarks/{id}` `title` means the title you chose**, and writes `title_override`, as it does today.
The request and response shapes are unchanged, so the contract version stays at 1 (ADR 0008).
Only which column `POST` writes changes.

**A re-save refreshes `saved_title`** when the client sends a non-empty title.
Saving is an explicit act on the page as it is now, and titles do change: an issue gets renamed, a draft gets published.
It never touches `title_override`, which is yours.

**A context-menu link save sends no title.**
The client does not know the linked page's title, and a guess is worse than nothing because it outranks the crawled title.

**Existing rows move** in the migration that adds the column: every non-empty `title_override` becomes `saved_title`, and `title_override` is cleared.
No client has ever offered a way to type a title, so every existing override was written by a client, not a person.
The real database holds one save, so this is a statement about correctness rather than a data migration of any size.

## Consequences

- Revision `0003` adds `user_bookmark.saved_title text`, moves existing overrides into it, and moves `REQUIRED_SCHEMA_REVISION`.
  The SQL file and `models.py` both change, and the schema-diff test holds them together.
- The M3 worker writes `bookmark.title` and nothing else to do with titles.
  It never reads or writes per-save columns, which keeps crawling per URL (ADR 0001).
- Tab titles carry noise the crawled title does not: a leading "(3) " unread count, a " - Site Name" suffix.
  That is cosmetic, per save, and can be cleaned at display or at save time later without a schema change.
- The popup can later show "Edit title" backed by `PATCH`, and an edited title then survives every re-save and every crawl, which it could not while the extension owned the override column.
- Searching by title means searching all three columns.
  `GET /bookmarks?q=` already reads `title_override` and `bookmark.title`, and gains `saved_title`.
