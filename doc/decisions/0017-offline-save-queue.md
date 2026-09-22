# 0017 - Saves made while the API is away are kept and delivered later

- **Date:** 2026-09-22
- **Status:** Accepted
- **Builds on:** [ADR 0016](0016-local-history-backend-on-action.md) (the API only on action, `history.db`), [ADR 0001](0001-two-level-bookmark-model.md) (a save is keyed by page), [ADR 0005](0005-versioning-and-compatibility.md) (the contract check)
- **Sketch:** [`m5-offline-save-queue.md`](../m5-offline-save-queue.md)

## Context

Since ADR 0016 the browser contacts the API only when you act, which makes a save the one moment the API has to be there.
Locally it often is not: it runs while `make api-dev` does.
A save made while it is down fails today.
The sheet opens on "Cannot reach ..." with nothing to save into, a quick save turns the button into a warning, and the page is lost unless you remember it.

Two things make a queue simple here:

- **`POST /bookmarks` is an upsert keyed by the page** (`UNIQUE (url_hash)`), merging tags into the one row.
  Delivering a save twice, or one the server already has, never makes a second row, so at-least-once delivery is correct and no exactly-once machinery is needed.
- **`history.db` already exists**, survives restarts, and already records which pages this browser saved.

## Decision

### What is queued

**Saves, from the save sheet and from quick save.**
Nothing else.

**Each pending save keeps:**

- the page, as `pageKey` has it;
- the title seen (ADR 0010);
- the tags;
- when you saved it;
- how many times delivery was tried;
- the last error.

**Saves of one page combine.**
A second save of a page already waiting becomes one entry, with the union of the tags and the later title, as the server would merge them anyway.

**Tag removals are not queued.**
Removing a tag needs the bookmark's id, which is usually unknown offline, and ordering a queued removal against queued saves is where a simple queue stops being simple.
Removal is rarer than saving, and nothing is lost by waiting for it.
Offline, the sheet shows the tags it knows, without their remove buttons, and says why.

### What counts as offline

Only an API that did not answer.
A refusal is said at once, as it is today: queueing it would only move the refusal to a moment when nobody is looking.

| Outcome | Queued? |
| --- | --- |
| Network error or timeout (status 0) | Yes |
| 502, 504, or a 503 from something in front of the API | Yes |
| 503 "no API tokens configured", from the API itself | No: a Settings problem, said now |
| 401, 403 | No: the token, said now |
| 422 | No: this save, said now in the sheet |
| 2xx | Delivered |

The API client classifies each outcome as `offline`, `refused` or `done`, so the queue does not re-derive it from status codes.

### Where it is kept

A `pending_save` table in `history.db`, added as step 2 of its `user_version` migrations.
It is the browser's, like the rest of that file.
Delete browsing data leaves it alone: these are pages you chose to keep, as the saved marks are (ADR 0016).

### The save sheet when the API is away

The sheet still takes a save.

- **A notice at the top**, not an error in place of the sheet: "Can't reach your bookmarks API. This page will be saved when it's back."
- **The page's tags**, if `history.db` knows them, which it does for a page saved or looked up here.
  Otherwise it says it does not know them, rather than "Not saved yet", which may be false.
- **Autocomplete from the vocabulary as last fetched.**
  `history.db` keeps it each time the sheet loads it.
  A stale vocabulary costs a suggestion, never a save.
- **Enter queues the save.**
  The sheet closes, and the button shows the page as waiting.

A quick save while the API is away queues too.

### What the button shows

Two states beside `saved` and `savable`:

- **Waiting**: saved here, not yet delivered.
  The saved icon with a small clock, and the tooltip "Saved here, waiting for your bookmarks API", with the tags.
  A page already saved with more tags waiting shows as waiting, with the union of both.
- **Refused**: the server refused a queued save when it came back, a 422 on a tag say.
  The warning icon and the server's reason.
  Opening the sheet shows that save, to fix its tags and save again, or drop.

### When delivery is tried

Delivering a save you made is still acting on your action, so it keeps to ADR 0016: the API hears about pages you chose to keep, just later.
Nothing is sent while nothing waits.

- **At launch**, if anything waits.
- **Before any action that reaches the API**, since the API has just been asked for.
- **On a timer while anything waits**, after 1, 2, 5 and 10 minutes, then every 10 minutes.
  Gentler than the crawl worker's schedule (ADR 0012): the likely cause is that `make api-dev` is not running, which ends when you start it.
- **When the network comes back**, from Electron's `net.isOnline()` and its change events.

**One flusher for the app, not one per window.**
It first checks the contract (ADR 0005), as any first action does.
Then it delivers the oldest save first, one at a time.
It stops at the first outcome that means still offline, and moves past a refused one.
A refused save is not retried until it is saved again or dropped.

**Delivered to the API configured at the time of delivery.**
With one user and one library, an address changed in Settings while saves waited is a correction, not a different library.

**A save's date is when it reaches the API.**
The server sets `created_at` on arrival, so a page saved offline on Monday and delivered on Wednesday is dated Wednesday.
An optional `saved_at` on `POST /bookmarks` would fix that without a contract bump, and waits until something shows by when a page was saved.

### Seeing what waits

**File > Saves Waiting (N)**, beside Save Page with Tags and Quick Save, present only while something waits.
It opens a card in the overlay listing each waiting or refused save: its title and site, its tags, when you saved it, and its last error.
Each has Retry and Drop, and the card has Retry All.
Without it, a refused save on a page you never reopen would be invisible.

## Options not taken

- **Queue tag removals too, by page, resolving the id when delivering.**
  Workable, and it brings ordering against queued saves: "add `x`, then remove `x`" must arrive in that order or be merged into "save without `x`".
  Not worth it for the rarer, less urgent operation.
- **Queue a page's whole intended tag set.**
  The most general, and it needs a "set these tags" call (`PUT`) the API does not have, which is a contract change.
- **Queue every failure, refusals included.**
  A 403 or a 422 is an answer; retrying it later only hides it from the moment you could act on it.
- **Keep each save for the API address it was made for.**
  Right if one browser fed several libraries.
  This one feeds one, and a changed address is a fixed typo, as the 8080 port was on 2026-09-21.
- **Add `saved_at` now.**
  It touches the API and its schema for a date nothing yet displays by.
- **A queue in its own file.**
  `history.db` is already the browser's local store, with migrations, and already holds the saved marks the queue updates.
- **The list of waiting saves in Settings, or in the History menu.**
  Settings is about the connection, not your pages.
  History is where you have been, not what you kept.
  Saving lives in the File menu, so what is still being saved does too.

## Consequences

- A save no longer depends on the API being up at that moment.
  Starting `make api-dev` later delivers what waited, within a minute of launch or of the next action.
- The browser may contact the API without a click, but only to deliver saves you made, and only while any wait.
  The traffic test from 0.5.0 still holds while nothing waits, and gains a case for delivery.
- A page saved offline shows its tags from what you typed, not from the server, until delivery.
  A tag the server would rename through an alias (ADR 0014) shows as typed until then.
- The extension has the same failure and no queue.
  That is its own decision.

## Implementation notes

Where building it refined the decision above.

- **The API client says whether anything answered**, on `ApiError.offline`.
  The API's own 503 is told from a gateway's by its JSON `detail`, which the API always sends and a proxy's error page does not.
- **The attempt that found the API away counts.**
  A save queued after a failed request starts at one attempt, with that request's error, so the list says what went wrong from the first.
- **The contract check moved out of the window into one `Connection` for the app**, which the queue shares, and callers asking at once share one `/health`.
- **"Before any action" starts a delivery beside the action, without waiting for it.**
  The action would fail the same way if the API were away, and waiting on the queue first would only delay an action that can succeed.
- **Saving Settings delivers what waits.**
  ADR 0016 has saving Settings send nothing, and it still sends nothing when nothing waits.
  When saves wait, a corrected address is the likeliest reason, so they go at once rather than on the next timer.
- **Electron's main process has no "back online" event.**
  The chrome's `online` event is passed on instead, and waking from sleep counts too (`powerMonitor`'s `resume`).
- **Tags queued while a delivery is on its way are not lost.**
  Each pending save has a version that moves with every change.
  A delivered save is removed only if its version is unchanged; otherwise the flush goes round again for the newer tags.
- **The Saves Waiting card updates in place as saves go**, rather than being rebuilt, so its focus and what it is saying survive each delivery, and it closes once nothing waits.
- **Fixing a refused save in the sheet saves it straight away when the API is there**, and drops the refused entry.
  It replaces the queued tags only if the API is still away.
