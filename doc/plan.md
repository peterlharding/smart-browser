# Smart-Browser — Plan

> Living document. Design rationale is in [`architecture.md`](architecture.md); the
> measurements behind it are in [`audit-2026-09-20.md`](audit-2026-09-20.md); settled
> decisions are in [`decisions/`](decisions/).

## Milestones

| # | Deliverable | Why here | Status |
| --- | --- | --- | --- |
| **M0** | Monorepo, API v2, clean schema, extension with tag-on-save, release process, CI | Tagging at the moment of saving is the product; everything else supports it | **done** |
| **M1** | Identity: OAuth for Google and GitHub, token issue and rotation | API tokens are a stand-in; real sign-in replaces them | deferred — see below |
| **M3** | Crawler: titles, text, embeddings. `bookmark_content`, pgvector | Nothing downstream works without extracted content | **done** |
| **M4** | AI categorization: suggestions on save, backfill, review queue for proposals | Tagging stops depending on you thinking of the tag | not started |
| **M5** | Electron shell: tabs, omnibox, OAuth sign-in, save sheet | First point a browser beats Chrome plus the extension | first slice done; OAuth, packaging and more to come |
| **M6** | Tag sidebar, multi-tag intersection, hybrid search | The thing you actually wanted | not started |

**The gaps are deliberate.** M2 was an importer from the predecessor and M7 retired its
`/xyzzy` endpoint; both are out of scope now that the predecessor will be brought into line
with this project rather than the reverse (ADR 0007). Surviving milestones keep their
numbers so that references to M3 and M4 in earlier ADRs stay correct.

M0, M3 and M4 are worth doing even if the browser never ships. That's deliberate: the
extension already delivers the core interaction, and a browser over an untagged corpus
would be a browser over an empty index.

**M1 is deferred behind M3 — 2026-09-21.** OAuth replaces a bearer token that works, for
a single user, on a client that already exists: real work with no user-visible result. It
is also blocked on a deployment decision that has now gone the other way — the API runs
locally, where an OAuth callback has nothing to call back to. M3 needs none of that, feeds
M4, and improves what you already use every day. OAuth lands when M5 gives it something to
sign in to.

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
`/api/v1/docs`. Until this ran, M0 was *assembled*, not *working*: three faults stood
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

Also fixed on the way: `/api/v1/docs` had no Authorize dialog, because auth read the
`Authorization` header by hand instead of declaring a security scheme — so the docs page
offered a bare header field, which invites `Bearer: <token>` and a 401.

**The database is no longer empty** — it holds what that first save put there. Nothing
bulk-imports; see ADR 0007.

---

## M3 — done

**Decided:** a queue in Postgres, drained by a worker
([ADR 0009](decisions/0009-crawl-queue-in-postgres.md)); the options and what each costs
are in [`m3-crawler-options.md`](m3-crawler-options.md).

Done so far — revision `0002`: `bookmark_content` (text, generated `tsvector`, 384d
embedding), `job_state`, `crawl_job`, and the enqueue inside the save transaction.
`make db-bootstrap` installs pgvector, which a migration cannot do for itself.
Revision `0003` separates the title seen at save time from the title you chose, so the
titles the worker fetches are displayed rather than shadowed
([ADR 0010](decisions/0010-title-seen-at-save.md)).

The crawl worker drains the queue ([ADR 0012](decisions/0012-crawl-worker.md)): `make
worker`, with `make crawl-backfill` for saves made before the queue and `make
crawl-status` to see it working. Its first real run found the one real save behind HTTP
Basic auth: `failed`, 401 recorded, and the save still titled by what the browser saw.

The embedding pass turns that text into vectors ([ADR
0013](decisions/0013-embeddings.md)): `make embed`, a separate process running
`bge-small-en-v1.5` through `fastembed`, re-embedding whatever `bookmark_content.model`
says was written by another model or recipe. End to end on a scratch database, two
articles about Postgres scored 0.75 against each other and 0.46 against a bread recipe.

Next is M4, which the open questions below still block.

**Unblocked — 2026-09-21.** pgvector 0.8.5 is available in the running container, so no
container swap. It is not a trusted extension, so installing it needs `postgres`, not
`api`: M3 starts with a one-time bootstrap step and a migration that asserts rather than
creates. Everything after that runs as `api`, verified.

---

## M5 — first slice done

**Moved ahead of M4 — 2026-09-21.** M4 waits on the open questions below, and the shell
needs only the API as it is.

The first slice ([ADR 0015](decisions/0015-electron-shell.md)) is in `apps/browser/`: tabs
with titles and favicons, restored on the next launch; an omnibox that visits or searches;
Chrome's shortcuts; the save sheet on `⌘⇧B`, quick save on `⌘⇧S` and a saved-state
indicator; settings with a connection test and the token in the Keychain; and the contract
check ADR 0005 promised. `make browser-dev` runs it; `make test-browser-e2e` drives the
built app against the real API on the test database.

**Local history, and the API only on action — 2026-09-22**
([ADR 0016](decisions/0016-local-history-backend-on-action.md)). Using the first slice showed
the browser asking the API about every page loaded; it now sends nothing while you browse,
and the save button shows what this browser knows. Where you have been is kept locally in
`history.db`: a History menu beyond Chrome's (full history, search, a site's history,
recently closed tabs with ⇧⌘T, recent pages, a submenu per earlier day, Delete Browsing
Data), and a history page laid out as Chrome's.

**Offline save queue — 2026-09-22** ([ADR 0017](decisions/0017-offline-save-queue.md),
sketched first in [`m5-offline-save-queue.md`](m5-offline-save-queue.md)). A save made
while the API is away waits in `history.db` and is delivered when it answers; the save
button shows it waiting, and File > Saves Waiting lists what is still to go.

**Packaging and signing — 2026-09-22** ([ADR 0018](decisions/0018-packaging-and-signing.md),
sketched first in [`m5-packaging.md`](m5-packaging.md)). `make browser-release` builds a
signed, notarized `Smart-Browser.app`, with a DMG and a zip for each release; a build run
from the repo has its own `Smart-Browser Dev` profile. Notarizing waits on storing the
credentials once, as RELEASING.md describes.

Still to come in M5: auto-update (`update-electron-app`, from the zip each release now
carries), downloads, and OAuth sign-in (with M1). The tag sidebar is M6.

**Possible enhancements** (not scheduled):

- **Say which API a rejected token was tried against.** Settings reports "Token rejected"
  whenever `/tags` answers 403, but a mistyped port can reach another server that answers
  like this API, and the message then blames the token for a wrong address (seen
  2026-09-21: Settings pointed at 8080 when `make api-dev` had moved to `API_PORT`, 8085,
  and something on 8080 answered `/health` and refused the token). `/health` needs no token and has already answered by then, so the message
  could name what it reached: "Reached API 0.x.y at `http://127.0.0.1:NNNN`, but it
  rejected this token".
- **Stop answering "not saved" with a 404.** `GET /bookmarks/lookup` returns 404 for a
  page you have not saved, a normal answer that fills the API's log with `404 Not Found`
  lines for every page browsed (seen 2026-09-21). Since ADR 0016 the browser looks a page
  up only when the save sheet opens, so the noise is much smaller. A 200 with an empty body, or a
  `{"saved": false}` shape, would read as what it is. It changes a response both clients
  depend on, so it is a contract version bump (ADR 0005, ADR 0008), best made alongside
  another change that needs one.

---

## Open questions

### 1. Which LLM for the backfill? *(blocks M4)*

The v1 code uses `gpt-4o`, heavier than this task needs. The vocabulary is constrained and the
output is structured, so a small model should do. Worth benchmarking two candidates against the
1,817 hand-tagged bookmarks — you have ground truth, so measure rather than guess.

### 2. Deployment target? *(settled for now — 2026-09-21)*

**Local only**, on the Mac at `127.0.0.1:8000`. This is a decision with an expiry date:
OAuth needs a callback a provider can reach, so M1 cannot start until the question is
reopened — which is part of why M1 now sits behind M3. The Linux server the predecessor
runs on is the obvious candidate when it is.

### 2a. ~~Rename `/api/v2` to `/api/v1`?~~ *(done — 2026-09-21)*

Renamed, with `API_CONTRACT_VERSION` to match: one client, one constant, one generated
contract file. [ADR 0008](decisions/0008-api-path-v1.md).

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
| 2026-09-21 | Crawl queue is a table in Postgres, drained by a worker | [ADR 0009](decisions/0009-crawl-queue-in-postgres.md) |
| 2026-09-21 | API path is `/api/v1`; contract version 1 | [ADR 0008](decisions/0008-api-path-v1.md) |
| 2026-09-21 | Local-only deployment for now; M1 deferred behind M3 | this plan, Milestones |
| 2026-09-21 | Title seen at save is per save, apart from the title you chose; you, then seen, then crawled | [ADR 0010](decisions/0010-title-seen-at-save.md) |
| 2026-09-21 | URL normalisation merges only spellings of the same resource; http and https only | [ADR 0011](decisions/0011-conservative-url-normalisation.md) |
| 2026-09-21 | Crawl worker: one page at a time, 10-minute lease, trafilatura, private addresses refused, robots.txt not consulted | [ADR 0012](decisions/0012-crawl-worker.md) |
| 2026-09-21 | Embeddings through fastembed, one vector per page from its opening 512 tokens, in its own process | [ADR 0013](decisions/0013-embeddings.md) |
| 2026-09-21 | Tag names: no comma, whitespace or control character, no length limit; aliases resolve on every path | [ADR 0014](decisions/0014-tag-names.md) |
| 2026-09-22 | The browser ships as a signed, notarized Smart-Browser.app, packaged by Electron's own tools; development has its own profile | [ADR 0018](decisions/0018-packaging-and-signing.md) |
| 2026-09-22 | Saves made while the API is away wait in history.db and are delivered when it answers | [ADR 0017](decisions/0017-offline-save-queue.md) |
| 2026-09-22 | Browsing history is local; the browser contacts the API only when you act | [ADR 0016](decisions/0016-local-history-backend-on-action.md) |
| 2026-09-21 | M5 moves ahead of M4, which waits on its open questions | this plan, M5 |
| 2026-09-21 | Electron shell: TypeScript, Svelte, Vite and esbuild; overlay view; token in main only; first slice | [ADR 0015](decisions/0015-electron-shell.md) |
| 2026-09-21 | First end-to-end save: extension → API → Postgres, verified in Swagger | this plan, M0 |
| 2026-09-20 | Schema on Alembic revisions; contract version separate from release version; compatibility enforced by checks, not numbers | [ADR 0005](decisions/0005-versioning-and-compatibility.md) |
