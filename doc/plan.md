# Smart-Browser — Plan

> Living document. Design rationale is in [`architecture.md`](architecture.md); the
> measurements behind it are in [`audit-2026-09-20.md`](audit-2026-09-20.md); settled
> decisions are in [`decisions/`](decisions/).

## Milestones

| # | Deliverable | Why here | Status |
| --- | --- | --- | --- |
| **M0** | Monorepo; API v2; auth on writes; release process and CI | Unblocks everything | **done** |
| **M0.5** | Clean schema; extension v2 with tag-on-save | Delivers the actual value — tagging at save time — without waiting for a browser | **done** |
| **M1** | Identity: OAuth for Google and GitHub, token issue/rotation | Tokens are a stand-in; real sign-in replaces them | not started |
| **M2** | Importer from the cleaned-up `bookmarks-pg` | Brings the corpus across, with dedupe and tag-alias work | not started |
| **M3** | Crawler: titles, text, embeddings; `bookmark_content` and pgvector | Nothing downstream works without extracted content | not started |
| **M4** | AI categorization: suggestions on save, backfill, review queue | Makes the corpus navigable — **the payoff step** | not started |
| **M5** | Electron shell: tabs, omnibox, OAuth sign-in, save sheet | First point the browser beats Chrome + extension | not started |
| **M6** | Tag sidebar, multi-tag intersection, hybrid search | The thing you actually wanted | not started |
| **M7** | Retire the v1 `/xyzzy` endpoint | Old clients converge | not started |

M0–M4 are worth doing even if the browser never ships. That's deliberate.

**What moved, and why.** Two reorderings, both driven by the same instinct: get something
usable sooner.

The extension moved to the front (was M7). Tagging at save time is the entire point of the
project, and it needed no browser — only an API and a popup. It now exists.

The schema migration became an *importer* (M2). The v1 tables are being cleaned up
separately, so the new API owns a clean database rather than accommodating the old one
(ADR 0006). That deleted a great deal: the advisory-lock id allocation, the lock that
serialised check-then-insert, the URL string fallback, and the `varchar(32)` tag cap. It
also made the no-duplicates promise a database constraint instead of a code convention,
which is what it should always have been.

---

## M0 and M0.5 — done

**API** (`apps/api/`), on a clean database built by Alembic revision `0001`:

- Bearer auth on **every** request. Reads included — bookmarks belong to a user, so there
  is no coherent anonymous read. With no tokens configured the API refuses everything
  rather than allowing it.
- `POST /bookmarks` is an upsert over `UNIQUE (url_hash)`: 201 the first time, 200 after,
  never a second row, whatever the URL's spelling and however many clients call at once.
- `GET /bookmarks/lookup` answers "have I saved this?" without writing anything.
- Tag intersection (`?tags=a,b&mode=all`) and `?untagged=true`.
- Every read scoped through `user_bookmark`; `test_scoping.py` guards the invariant.
- A schema guard that refuses to start against the wrong Alembic revision.

**Extension** (`apps/extension/`), MV3:

- `⌘⇧B` opens a save sheet: existing tags, autocomplete ranked by your usage, `Tab` to
  accept, `Enter` to save. Opening it is a lookup, never a save.
- `⌘⇧S` quick-saves with no tagging, badging amber to mark an untagged save.
- Options page with a connection test reporting API, contract and schema versions.

**Not yet pointed at a live database.** `make migrate` creates the schema; there is no
data in it until M2.

---

## Open questions

### 1. Which LLM for the backfill? *(blocks M4)*

The v1 code uses `gpt-4o`, heavier than this task needs. The vocabulary is constrained and the
output is structured, so a small model should do. Worth benchmarking two candidates against the
1,817 hand-tagged bookmarks — you have ground truth, so measure rather than guess.

### 2. Deployment target? *(blocks M5)*

Does `bookmarks.performiq.com` stay the target, with the browser talking to it over the
internet? It has to, now: OAuth sign-in requires the backend to be reachable, so a
bundled-local-API option is off the table for first login. Confirms the offline queue matters.

### 3. Tag hierarchy? *(blocks M4 — changes the prompt)*

`parent_id` is in the schema but unused. Should `python` imply `programming`? It changes how the
AI prompt is built and how sidebar filters compose.

### 4. Private tags? *(not blocking)*

ADR 0002 chose a global vocabulary. Adding a per-user private namespace later is additive
(`tag.owner_id` nullable, NULL = global). Worth revisiting only if a second real user wants it.

---

## Decisions log

| Date | Decision | Where |
| --- | --- | --- |
| 2026-09-20 | Electron as the browser shell | `architecture.md` §1 |
| 2026-09-20 | Hybrid categorization: LLM backfill, embeddings steady-state | `architecture.md` §3 |
| 2026-09-20 | Extensions stay first-class clients of API v2 | `architecture.md` — guiding constraint |
| 2026-09-20 | Monorepo: browser and API in one repo | this repo |
| 2026-09-20 | Multi-user; split the URL from the save | [ADR 0001](decisions/0001-two-level-bookmark-model.md) |
| 2026-09-20 | Global tag vocabulary, ownership on the link | [ADR 0002](decisions/0002-global-tag-vocabulary.md) |
| 2026-09-20 | OAuth through the backend; Google + GitHub | [ADR 0003](decisions/0003-oauth-via-backend.md) |
| 2026-09-20 | Local `bge-small-en-v1.5`, 384d, behind a config value | `architecture.md` §2 |
| 2026-09-20 | Clean schema; no v1 compatibility; `UNIQUE (url_hash)` enforces no-duplicates | [ADR 0006](decisions/0006-clean-schema.md) |
| 2026-09-20 | Reads require a token: per-user data has no anonymous read | [ADR 0006](decisions/0006-clean-schema.md) |
| 2026-09-20 | ~~One version for the monorepo~~ | [ADR 0004](decisions/0004-single-version-monorepo.md) — superseded |
| 2026-09-20 | Schema on Alembic revisions; contract version separate from release version; compatibility enforced by checks, not numbers | [ADR 0005](decisions/0005-versioning-and-compatibility.md) |
