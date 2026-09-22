# M5 — the offline save queue

> Sketch, not a decision.
> What the queue has to do, what it can lean on, and the choices still open, so the ADR (0017) can be written from a settled list rather than discovered while building.
> Its recommendations were accepted on 2026-09-22 and drafted as [ADR 0017](decisions/0017-offline-save-queue.md).

## Why now

Since 0.5.0 the browser contacts the API only when you act (ADR 0016).
That makes a save the one moment the API has to be there, and locally it often is not: it runs while `make api-dev` does, and not otherwise.

Today a save made while the API is down fails.

- **The save sheet** opens with "Cannot reach `http://127.0.0.1:8000`: fetch failed" and nothing to save into.
- **A quick save** turns the save button into a warning, and nothing is kept.

The page is lost unless you remember it and save it again later.
Losing a page is the one failure a bookmarking tool exists to prevent.

## What the queue can lean on

**A save is an upsert, and replaying it is harmless.**
`POST /bookmarks` is keyed by the page (`UNIQUE (url_hash)`, ADR 0001): the first save creates the row, and every later one merges its tags into the same row.
Sending a queued save twice, or sending one the server already has, never makes a second row.
So the queue needs no exactly-once machinery: at-least-once delivery is correct.

**Two saves of one page combine.**
Their tags merge on the server anyway, so two queued saves of the same page can become one entry with the union of their tags and the later title.

**There is already a local store.**
`history.db` (ADR 0016) survives restarts and already records which pages this browser saved.
A pending save is a new table in it, added as the second step of its `user_version` migrations.

**The API client already tells "absent" from "refused".**
A network failure or timeout raises `ApiError` with status 0.
An answer (401, 403, 422) has its status.

## What counts as offline

Only an API that could not be reached, and so did not answer, is offline.

| Outcome | Meaning | Queue it? |
| --- | --- | --- |
| Network error or timeout (status 0) | Nothing answered | Yes |
| 502, 503 from a proxy, 504 | Something in front answered for it | Yes |
| 503 "no API tokens configured" | The API is up and refusing everything | No: a Settings problem, said now |
| 401, 403 | The token is wrong | No: said now, as today |
| 422 | This save cannot be accepted, such as a tag with a comma | No: said now, in the sheet |
| 2xx | Saved | Delivered |

A refusal is not offline: queueing a save the server has already refused would only move the refusal later, to a moment when nobody is looking.

## What is queued

**Saves: the sheet and quick save.**
Each keeps:

- the page;
- the title seen (ADR 0010);
- the tags;
- when you saved it;
- how many times delivery has been tried;
- the last error, if any.

**Tag removals: the open question.**
`DELETE /bookmarks/{id}/tags/{tag}` needs the bookmark's id, and offline the id is known only for a page the sheet looked up earlier.
There are three ways:

1. **Do not queue removals.**
   Offline, the sheet shows the tags it knows but cannot remove them, and says why.
   This is the simplest, and removal is rarer than saving and less urgent: nothing is lost by waiting.
2. **Queue removals by page**, and look the id up when delivering.
   This needs care with ordering: a save that adds `x` and a later removal of `x` must be delivered in that order, or merged into "save without `x`".
3. **Queue the page's intended tag set**, and deliver it as a save plus the removals that set implies.
   This is the most general, and it needs a "set these tags" call the API does not have (`PUT` instead of `POST`), which is a contract change.

Option 1 is the recommendation: it removes nothing you might want later, and it keeps the queue to one kind of entry.

## The save sheet when the API is away

The sheet needs three things from the API: whether the page is saved, its tags, and your vocabulary for autocomplete.
Offline it has none of them, and it should still take a save.

- **It says so at the top**, without turning the whole sheet into an error: "Can't reach your bookmarks API. This page will be saved when it's back."
- **Tags already known for the page** come from `history.db`, if this browser saved or looked it up.
  Otherwise the sheet says it does not know them, rather than showing "Not saved yet", which may be false.
- **Autocomplete** comes from the vocabulary as it was last fetched, kept in `history.db` each time the sheet loads it.
  A stale vocabulary costs a suggestion, never a save.
- **Enter saves into the queue**, the sheet closes, and the button shows the page as waiting.

## What the button shows

Two new states beside `saved` and `savable`:

- **Waiting**: saved here, not yet delivered.
  It looks like the saved icon with a small clock, and its tooltip reads "Saved here, waiting for your bookmarks API (N tags)".
- **Refused**: a queued save the server refused when it came back, such as a 422 on a tag the rules now forbid.
  It shows the warning icon and the server's reason, and opening the sheet shows the save to fix or drop.

A page both saved and waiting, because a later save added tags that are still queued, shows as waiting: the tags you see are the union of the two.

## When delivery is tried

Replaying a save you made is still acting on your action, so it fits ADR 0016.
The API hears only about pages you chose to keep, just later.
What delivery must never do is poll while nothing is waiting.

When to try, and why:

- **On launch, if anything is waiting.**
  The API may have come back while the browser was closed.
- **On any action that reaches the API**, before the action itself.
  The API has just shown it is there.
- **On a timer while anything is waiting**, with backoff: 1, 2, 5, 10 minutes, then every 10 minutes.
  This is gentler than the crawl worker's schedule (ADR 0012), because the likely cause is "`make api-dev` is not running", which ends when you start it.
- **When the network comes back**, from Electron's `net.isOnline()` and the `online` event.
  This is cheap, though it does not help locally: the API on `127.0.0.1` is "offline" while the Mac is online.

Delivery is **one flusher for the app**, not one per window: saves go oldest first, one at a time, and it stops at the first failure that means "still offline".
It checks the contract (ADR 0005) first, as any first action does.

## Smaller questions

- **When a page counts as saved.**
  `created_at` is set by the server when a save arrives, so a page saved offline on Monday and delivered on Wednesday is dated Wednesday.
  Options:
  - Accept it.
  - Add an optional `saved_at` to `POST /bookmarks`, taken only when a save creates the row and clamped to the past.
    That is an additive field, so the contract version stays 1.
  - Record the delay only in the browser.

  It matters for "saved this week" views later, and hardly at all now.
- **Settings change while saves wait.**
  A pending save was made for the API configured then.
  It could be delivered to whatever API is configured when it goes, which is simplest and right when a port was fixed, or held for the address it was made for.
  The recommendation is to deliver to the current API: with one user and one library, a changed address is a correction, not a different library.
- **Seeing everything that waits.**
  A short list, in Settings or as a History menu item ("Saves Waiting (3)"), with each page's tags and last error, and a way to retry or drop one.
  Without it, a refused save on a page you never reopen is invisible.
- **Delete browsing data leaves the queue alone.**
  Saves are what you chose to keep, as the saved marks are (ADR 0016).
- **The extension.**
  It has the same failure and no queue.
  This sketch is the browser's; whether the extension gets one is its own question.

## Testing it

The recording proxy the end-to-end suite already puts in front of the API gains a switch that makes it refuse connections, and one that makes it answer 422.

- **Saving while it refuses** queues the save, and the button shows the page as waiting.
  The proxy records nothing.
- **Switched back on**, the queue delivers without being asked, oldest first.
  Each save arrives once, and the API holds one row per page with the merged tags.
- **Queued, then quit and relaunched**, the save is still waiting, and is delivered once the API is reachable.
- **A save the API refuses on delivery** shows as refused on the page, with the server's reason, and is not retried until it is fixed.
- **Browsing while saves wait** sends nothing except the deliveries themselves.
  The traffic test from 0.5.0 keeps holding.

In unit tests, the queue's store and its schedule use the clock and the fetcher as parameters, as `history.ts` and the API client already do.

## Recommendation

1. Queue saves (the sheet and quick save), in `history.db`, combining saves of one page.
2. Do not queue tag removals; the sheet says why it cannot remove offline.
3. Queue only when nothing answered (status 0, 502, 504, a proxy's 503); refusals are said at once, as now.
4. Deliver on launch, before any action, and on a backing-off timer while anything waits, from one app-wide flusher.
5. Show waiting and refused on the save button, and list what waits somewhere you can find it.
6. Deliver to the API configured at the time; leave `saved_at` for later unless "when saved" matters sooner.

## If that is chosen, the order of work

1. The ADR (0017), from this sketch and the answers to its questions.
2. `pending_save` in `history.db` (migration step 2), with unit tests: add, combine, take oldest, mark attempted, mark refused, drop.
3. Classifying outcomes in the API client (offline, refused, saved), unit-tested against a fake fetcher.
4. Queueing from quick save, then from the sheet, with the sheet's offline state and the cached vocabulary.
5. The flusher and its schedule.
6. The button's waiting and refused states, and the list of what waits.
7. End-to-end: the proxy's switches, and the cases under Testing it.
