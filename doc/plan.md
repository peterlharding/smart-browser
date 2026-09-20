# Smart-Browser — Plan

> Living document. Design rationale is in [`architecture.md`](architecture.md); the
> measurements behind it are in [`audit-2026-09-20.md`](audit-2026-09-20.md); settled
> decisions are in [`decisions/`](decisions/).

## Milestones

| # | Deliverable | Why here | Status |
| --- | --- | --- | --- |
| **M0** | Monorepo; API v2 over the existing schema; auth on writes; additive safety migration | Unblocks everything; closes the open `/xyzzy` endpoint | **done** |
| **M1** | Identity: `app_user`, `user_identity`, OAuth for Google and GitHub, token issue/rotation | Multi-user means ownership must exist *before* rows are migrated into it | not started |
| **M2** | Schema migration: dedupe, alias seeding, split into `bookmark` / `user_bookmark` | Constraints before volume; everything existing becomes plh's | not started |
| **M3** | Crawler: titles, text, embeddings for 7,256 URLs | Titles are 96% missing; nothing downstream works without this | not started |
| **M4** | AI backfill of 7,655 untagged bookmarks; review queue for proposals | Makes the corpus navigable — **the payoff step** | not started |
| **M5** | Electron shell: tabs, omnibox, OAuth sign-in, save sheet with suggested tags | First point the browser beats Chrome + extension | not started |
| **M6** | Tag sidebar, multi-tag intersection, hybrid search | The thing you actually wanted | not started |
| **M7** | Retarget Chrome/Firefox extensions at v2; retire `/xyzzy` | Old clients keep working throughout, then converge | not started |

M0–M4 are worth doing even if the browser never ships. That's deliberate.

**What moved.** Identity was inserted at M1 and everything shifted down. Going multi-user means
`user_bookmark` needs a `user_id` to point at, so `app_user` has to exist before the migration
runs — otherwise the 9,472 existing rows get migrated twice.

---

## M0 — done

Delivered in `apps/api/`:

- FastAPI v2 at `/api/v2`, running against the **current** schema with no migration.
- Bearer auth on every write. Writes return 503 when no tokens are configured, rather than
  allowing them.
- Idempotent `POST /bookmarks` matching on the normalised URL.
- `urlnorm.py` with 24 tests — the foundation M2's dedupe depends on.
- Alembic, with revision `0001` (additive only): sequences to replace `SELECT MAX(id)+1`,
  plus the index on `bookmark_tag(tag_fk)` that has never existed. The DDL stays in
  `migrations/sql/` so it is reviewable as SQL.
- `schema_guard`: the API refuses to start when the database is not at the revision the code
  requires, and `/api/v2/health` reports the contract version for the browser to assert.
- `packages/shared-types/openapi.json` for generating the Electron client — committed, and
  CI fails if it goes stale.
- Test suite: 57 API tests and 9 for the version script, none needing infrastructure, plus an
  opt-in Postgres suite (`-m postgres`) covering sequences, advisory locks and the migration.
- Release process: `CHANGELOG.md`, `release_notes/`, `scripts/version.py`, `make check`, and
  a CI workflow running the same gate.

**Not yet applied to the live database.** Run `make migrate` when ready; the v1 app keeps
working with it in place. The live database has never been stamped by Alembic, so the first
run needs either `make migrate` (applies and stamps) or, if the SQL was already applied by
hand, `make migrate-stamp REV=0001`. The API will refuse to start until one of those has
happened — deliberately.

## M1 — identity

1. `app_user`, `user_identity`, `oauth_state`, `refresh_token` (see `architecture.md` §2, §2a).
2. Register OAuth clients: Google Cloud Console, GitHub Developer Settings. Callback is the
   **backend's** URL, not a loopback — the app never talks to the provider directly.
3. Implement the flow in ADR [0003](decisions/0003-oauth-via-backend.md). PKCE S256 on the
   provider leg; single-use, short-expiry `state` and handover code.
4. Refresh-token rotation with reuse detection: a replayed token revokes the whole chain.
5. Map the existing API tokens to a user so the extensions keep working unchanged.
6. Seed `app_user` with plh — the owner of everything in M2.

**Test the invariant here, not later:** a user must not be able to read another user's saves
through any route, including by guessing a `bookmark_id`.

## M2 — schema migration

Order matters. Cleanup must precede constraints, or the constraints won't apply.

1. **Normalise and dedupe URLs.** `urlnorm.normalise()` is already written and tested. Hash to
   `url_hash`. Then **merge, don't delete**: for each duplicate group keep the earliest `id`,
   union the tag links onto it, take the earliest `used` as `created_at` and the latest as
   `last_visited_at`, soft-delete the rest. 2,216 rows collapse. Keep `bookmark_merge(old_id,
   new_id)` so nothing is unrecoverable.

2. **Seed `tag_alias`.** Work the 32 near-duplicate pairs from the audit as a *review queue*,
   not a script — `html`/`html5`, `angular`/`angular2`, `auth`/`oauth`, `books`/`ebooks`,
   `network`/`networks` are legitimately distinct and must not be merged. Choose canonical
   spellings by usage count and re-point the loser's links. Drop the blank tag and its 43 links.

3. **Repair the 12 orphan rows** in `bookmark_tag` — delete them, there's nothing to point at.

4. **Split into two levels.** Every surviving row becomes one `bookmark` (the URL) plus one
   `user_bookmark` owned by plh. `bookmark_tag` re-points from `bookmark_fk` to
   `user_bookmark_id`.

5. **Add constraints and indexes.** They will now apply cleanly.

**The dump is the test fixture.** 940 KB of real data beats anything synthetic, and every
number in the audit is an assertion you can write: 9,472 in, 7,256 `bookmark` rows out, 2,623
links preserved minus the 12 orphans and 43 blanks.

## M3 — crawler

Expect a meaningful fraction of 2015-era links to be dead. Record `http_status` so "never
fetched" is distinguishable from "410 Gone", and **do not auto-delete dead links** — an
unreachable bookmark is still a record of something you cared about, and many are recoverable
from archive.org later.

One crawl and one embedding per URL, not per save — that is the whole point of ADR 0001.

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
| 2026-09-20 | ~~One version for the monorepo~~ | [ADR 0004](decisions/0004-single-version-monorepo.md) — superseded |
| 2026-09-20 | Schema on Alembic revisions; contract version separate from release version; compatibility enforced by checks, not numbers | [ADR 0005](decisions/0005-versioning-and-compatibility.md) |
