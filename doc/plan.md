# Smart-Browser — Plan

> Living document. Design rationale is in [`architecture.md`](architecture.md); the
> measurements behind it are in [`audit-2026-09-20.md`](audit-2026-09-20.md); settled
> decisions are in [`decisions/`](decisions/).

## Milestones

| # | Deliverable | Why here | Status |
| --- | --- | --- | --- |
| **M0** | Monorepo, API v2, clean schema, extension with tag-on-save, release process, CI | Tagging at the moment of saving is the product; everything else supports it | **done** |
| **M1** | Identity: OAuth for Google and GitHub, token issue and rotation | API tokens are a stand-in; real sign-in replaces them | **next** |
| **M3** | Crawler: titles, text, embeddings. `bookmark_content`, pgvector | Nothing downstream works without extracted content | not started |
| **M4** | AI categorization: suggestions on save, backfill, review queue for proposals | Tagging stops depending on you thinking of the tag | not started |
| **M5** | Electron shell: tabs, omnibox, OAuth sign-in, save sheet | First point a browser beats Chrome plus the extension | not started |
| **M6** | Tag sidebar, multi-tag intersection, hybrid search | The thing you actually wanted | not started |

**The gaps are deliberate.** M2 was an importer from the predecessor and M7 retired its
`/xyzzy` endpoint; both are out of scope now that the predecessor will be brought into line
with this project rather than the reverse (ADR 0007). Surviving milestones keep their
numbers so that references to M3 and M4 in earlier ADRs stay correct.

M0, M3 and M4 are worth doing even if the browser never ships. That's deliberate: the
extension already delivers the core interaction, and a browser over an untagged corpus
would be a browser over an empty index.

**What moved, and why.** The extension came to the front, because tagging at save time is
the entire point and it needed no browser — only an API and a popup. It now exists, and
that is what made it reasonable to push the Electron shell back behind the categorization
work rather than ahead of it.

---

## M0 — done

**API** (`apps/api/`), on a schema created by Alembic revision `0001`:

- Bearer auth on **every** request, reads included — bookmarks belong to a user, so there
  is no coherent anonymous read. With no tokens configured the API refuses everything.
- `POST /bookmarks` is an upsert over `UNIQUE (url_hash)`: 201 the first time, 200 after,
  never a second row, whatever the URL's spelling and however many clients call at once.
- `GET /bookmarks/lookup` answers "have I saved this?" without writing.
- Tag intersection (`?tags=a,b&mode=all`) and `?untagged=true`.
- Every read scoped through `user_bookmark`; `test_scoping.py` guards the invariant.
- A schema guard that refuses to start against the wrong Alembic revision.

**Extension** (`apps/extension/`), MV3:

- `⌘⇧B` opens a save sheet: existing tags, autocomplete ranked by your usage, `Tab` to
  accept, `Enter` to save. Opening it is a lookup, never a save.
- `⌘⇧S` quick-saves with no tagging, badging amber to mark the untagged save.
- Options page with a connection test reporting API, contract and schema versions.

### Proven end-to-end — 2026-09-21

Save from the extension with tags, through the API, into Postgres, read back through
`/api/v2/docs`. Until this ran, M0 was *assembled*, not *working*: three faults stood
between the two, and every one of them was invisible to a green suite.

- **`API_TOKENS` was unset**, so the API refused every request with 503. That is the
  intended failure — an unconfigured deployment should be inert rather than public — but
  nothing in the setup path said so until a request hit it.
- **The extension's `fetch` was called on the wrong receiver.** `globalThis.fetch` held
  in a field and invoked as `this.fetch(...)` throws `Illegal invocation` in Chrome.
  Node's `fetch` does not check, so 41 passing tests could not see it. The suite now
  carries a stand-in as strict as the browser.
- **The API had no CORS handling**, which a browser client reports as a network error
  while the server log shows an ordinary 200.

The lesson is the one from the Postgres suite, in a second form: *a test that cannot
reach the failure is not evidence*. The first two faults lived in exactly the gap between
what the suite exercises (Node, SQLite, an injected fetch) and what runs (Chrome, a real
database, the browser's own fetch). Worth keeping in view for M5, where the Electron
shell adds a third runtime with the same property.

Also fixed on the way: `/api/v2/docs` had no Authorize dialog, because auth read the
`Authorization` header by hand instead of declaring a security scheme — so the docs page
offered a bare header field, which invites `Bearer: <token>` and a 401.

**The database is no longer empty** — it holds what that first save put there. Nothing
bulk-imports; see ADR 0007.

---

## Open questions

### 1. Which LLM for the backfill? *(blocks M4)*

The v1 code uses `gpt-4o`, heavier than this task needs. The vocabulary is constrained and the
output is structured, so a small model should do. Worth benchmarking two candidates against the
1,817 hand-tagged bookmarks — you have ground truth, so measure rather than guess.

### 2. Deployment target? *(blocks M1)*

Where does this run? OAuth sign-in needs the backend reachable from wherever the browser
is, so a bundled-local-API option is off the table for first login — which also confirms
the offline queue matters.

### 2a. Rename `/api/v2` to `/api/v1`? *(cheapest now, never cheaper)*

The `v2` is a fossil — it was v2 because the predecessor was v1. This is the first contract
version of a new system and the name is wrong. One client would need updating, which is as
cheap as it will ever get. Against: it is a contract change, and a wrong-but-stable name
costs nothing functionally.

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
| 2026-09-21 | First end-to-end save: extension → API → Postgres, verified in Swagger | this plan, M0 |
| 2026-09-20 | Schema on Alembic revisions; contract version separate from release version; compatibility enforced by checks, not numbers | [ADR 0005](decisions/0005-versioning-and-compatibility.md) |
