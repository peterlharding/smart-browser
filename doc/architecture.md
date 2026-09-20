# Smart-Browser — Architecture

> Target design. Evidence for these choices is in [`audit-2026-09-20.md`](audit-2026-09-20.md);
> sequencing and open questions are in [`plan.md`](plan.md).

## Goal

A browser wrapping the Chrome engine in which bookmarking is tag-first and multi-category, backed
by the existing FastAPI + Postgres service, with AI categorization that works on save rather than
as an afterthought.

## Guiding constraint

**The browser is a second client of the API, not a replacement for the extensions.** The existing
Chrome and Firefox extensions keep working against API v2 with no behavioural change. If the
browser turns out to be more work than it's worth, the result is still a much better bookmarks
system — which is the hedge that makes this project safe to start.

---

## 1. Shell: Electron

Electron is the only option that genuinely wraps the Chrome engine while letting you own the
chrome. `WebContentsView` (the replacement for the deprecated `BrowserView`) gives one Chromium
web contents per tab, composited under a UI written in HTML — so the tag sidebar, omnibox and
save flow are your own web app with privileged IPC.

Honest costs: ~150 MB binaries, and you inherit Electron's Chromium cadence, so security updates
mean shipping a new build. Acceptable for a personal tool; not for distributed software.

**Rejected:**

- **CEF via `cefpython`** — effectively unmaintained.
- **PySide6 / QtWebEngine** — would keep you in Python next to FastAPI, but lags Chromium by
  several versions and has essentially no extension support.
- **Tauri** — uses the system webview (WebKit on macOS), so it isn't the Chrome engine at all.
- **Chrome extension only** — no browser to build and it reuses what you have, but it can't own
  the omnibox or replace the bookmark UI, which is the point.

### Layout

```text
smart-browser/
├── src/main/          # Electron main process
│   ├── tabs.ts        # WebContentsView per tab, lifecycle, nav events
│   ├── ipc.ts         # typed channels, contextBridge surface
│   ├── api.ts         # API v2 client + offline queue
│   └── shortcuts.ts   # global save/search accelerators
├── src/preload/       # contextBridge only
├── src/renderer/      # the chrome: omnibox, tab strip, tag sidebar, save sheet
└── src/shared/        # types generated from the OpenAPI schema
```

### The parts that matter

- **Save sheet.** ⌘⇧B captures the current tab, POSTs it, and immediately shows suggested tags as
  chips. Accepting is one keystroke. This is the whole product; everything else supports this
  moment. It is the direct fix for 1.44 tags per bookmark.
- **Tag sidebar as navigation.** Tags aren't a property panel, they're how you move around: click
  `python` + `fastapi`, get the intersection, open results in tabs.
- **Offline queue.** The browser must save when the API is unreachable. A local SQLite queue that
  drains on reconnect. The extension has never had this and it's a real gap.
- **Security posture.** `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, a
  strict CSP on the chrome, and a `setWindowOpenHandler` that routes `window.open` into your tab
  model rather than spawning unmanaged windows. Never expose `ipcRenderer` wholesale.
- **Chrome extension support** exists in Electron but is partial and unofficial
  (`session.loadExtension`, MV2-leaning). Don't plan on running the existing extension inside it —
  the browser talks to the API directly.

---

## 2. Data model

Multi-user from the start (ADR [0001](decisions/0001-two-level-bookmark-model.md),
[0002](decisions/0002-global-tag-vocabulary.md)). Four ideas carry the value.

**The URL and the save are different things.** `bookmark` is the URL — global, unique on
`url_hash`, owned by nobody, crawled and embedded exactly once. `user_bookmark` is the personal
save. This keeps M2/M3 cost per-URL rather than per-user-per-URL, which matters because fetching
and embedding 7,256 URLs is the project's main expense.

**One tag vocabulary.** `tag` has no owner; ownership lives on the link. The existing 567 tags
become everyone's starting vocabulary and centroids pool across users.

**Provenance on the link.** `bookmark_tag` carries `source` and `confidence`, so AI suggestions
live beside your own tags without polluting them — "only tags I chose myself" is a `WHERE`
clause, not a second table.

**Aliases as data.** `tag_alias` replaces the hardcoded `corrections` dict. The model emits
`fontawesome`, the table resolves it to `font-awesome`.

```sql
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Identity ------------------------------------------------------------------

CREATE TABLE app_user (
    id           bigserial PRIMARY KEY,
    display_name text,
    email        citext,                    -- informational only, NEVER a join key
    avatar_url   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz,
    is_active    boolean     NOT NULL DEFAULT true
);

CREATE TABLE user_identity (
    provider         text   NOT NULL,       -- 'google' | 'github'
    provider_subject text   NOT NULL,       -- Google `sub`, GitHub numeric id: immutable
    user_id          bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    email_at_link    citext,                -- what the provider said, for audit only
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, provider_subject)
);
CREATE INDEX user_identity_user_idx ON user_identity (user_id);

-- The URL: global, one row per distinct page, crawled and embedded once ------

CREATE TABLE bookmark (
    id          bigserial PRIMARY KEY,
    url         text        NOT NULL,
    url_hash    bytea       NOT NULL UNIQUE,     -- sha256 of the normalised url
    title       text,                            -- canonical, from the crawl
    description text,
    site        text,                            -- registrable domain
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    fetched_at  timestamptz,
    http_status integer                          -- NULL = never fetched, != dead
);
CREATE INDEX bookmark_site_idx ON bookmark (site);

CREATE TABLE bookmark_content (
    bookmark_id bigint PRIMARY KEY REFERENCES bookmark(id) ON DELETE CASCADE,
    text        text,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(text,''))) STORED,
    embedding   vector(384),                     -- bge-small-en-v1.5; see plan.md
    model       text,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX bookmark_content_tsv_idx ON bookmark_content USING gin (tsv);
CREATE INDEX bookmark_content_emb_idx ON bookmark_content
    USING hnsw (embedding vector_cosine_ops);

-- The save: per user --------------------------------------------------------

CREATE TABLE user_bookmark (
    id              bigserial PRIMARY KEY,
    user_id         bigint      NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    bookmark_id     bigint      NOT NULL REFERENCES bookmark(id) ON DELETE CASCADE,
    title_override  text,                        -- your title beats the crawled one
    notes           text,
    saved_from      text,                        -- the client that posted it (was `host`)
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_visited_at timestamptz,
    visit_count     integer     NOT NULL DEFAULT 0,
    deleted_at      timestamptz,
    UNIQUE (user_id, bookmark_id)
);
CREATE INDEX user_bookmark_user_idx ON user_bookmark (user_id, created_at DESC)
    WHERE deleted_at IS NULL;

-- Tags: global vocabulary, per-user links -----------------------------------

CREATE TABLE tag (
    id          bigserial PRIMARY KEY,
    name        citext      NOT NULL UNIQUE,     -- citext kills the case dupes
    parent_id   bigint      REFERENCES tag(id) ON DELETE SET NULL,
    description text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tag_name_not_blank CHECK (length(trim(name::text)) > 0)
);
CREATE INDEX tag_name_trgm_idx ON tag USING gin (name gin_trgm_ops);

CREATE TABLE tag_alias (
    alias  citext PRIMARY KEY,
    tag_id bigint NOT NULL REFERENCES tag(id) ON DELETE CASCADE
);

CREATE TYPE tag_source AS ENUM ('user', 'ai', 'rule', 'import');

CREATE TABLE bookmark_tag (
    user_bookmark_id bigint      NOT NULL REFERENCES user_bookmark(id) ON DELETE CASCADE,
    tag_id           bigint      NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    source           tag_source  NOT NULL DEFAULT 'user',
    confidence       real,                       -- NULL for user tags
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_bookmark_id, tag_id)
);
CREATE INDEX bookmark_tag_tag_idx ON bookmark_tag (tag_id, user_bookmark_id);

CREATE TABLE tag_centroid (
    tag_id     bigint PRIMARY KEY REFERENCES tag(id) ON DELETE CASCADE,
    embedding  vector(384),
    n_samples  integer     NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
```

### Database platform

The target schema assumes **PostgreSQL 12 or newer**, and M3 assumes pgvector 0.5+:

| Feature | Needs | Used for |
| --- | --- | --- |
| `GENERATED ALWAYS AS ... STORED` | PG 12+ | `bookmark_content.tsv` |
| `citext`, `pg_trgm` | any supported version | tag names, fuzzy tag search |
| pgvector with `hnsw` | pgvector 0.5+ (PG 11+) | embedding search |

The 2025-05-10 dump reports `Dumped from database version 17.4` and
`docker/bookmarks-db/docker-compose.yml` pins `postgres:17`, so there is headroom. Confirm
the deployment target separately with `SELECT version();` — the dump and the compose file are
both dev-side evidence.

Note that the *schema* is much older than the server. `schema/bin/dump_mysql.sh` and
`db_converter.py` are still in the reference repo, and `models/bookmark.py` carries a
`mysql> desc bookmark;` transcript in its docstring. The shape being replaced — `integer`
ids with no default, `varchar(32)` tags, no foreign keys, no non-primary-key indexes — is a
mechanical MySQL conversion that arrived without sequences and never gained anything
Postgres-native. It is not a constraint the platform imposes.

### The invariant that matters

`bookmark` rows are shared between users. **Every read path must join through `user_bookmark`
filtered by `user_id`.** A query that reaches `bookmark` directly leaks the existence of other
people's saves — not their tags or notes, but the fact that a URL is in the system. This is the
one rule worth its own test rather than a code review.

### Other notes

- **`citext` on `tag.name` plus UNIQUE** prevents `Linux`/`linux` recurring; `tag_alias`
  handles misspellings.
- **`site` is new and `host` is renamed.** `site` is the registrable domain parsed from the
  URL; `saved_from` keeps `host`'s existing meaning. This is what makes list-by-domain work —
  see audit finding 6.
- **Soft delete** on `user_bookmark`, not on `bookmark`. Unsaving a page removes your save;
  the URL record and its embedding survive for everyone else.
- **`vector(384)`** matches `bge-small-en-v1.5` running locally. The dimension is a config
  value (`EMBEDDING_DIM`) so M2 can benchmark against the 1,817 hand-tagged bookmarks before
  committing; `bookmark_content.model` records what wrote each row so a re-embed is detectable.
- **`parent_id`** is present but unused pending the tag-hierarchy question in `plan.md`.

---

## 2a. Authentication

Google and GitHub, with **the backend as the confidential OAuth client** — the Electron app
never holds a provider secret or sees a provider token. Full reasoning and the rejected
alternatives are in ADR [0003](decisions/0003-oauth-via-backend.md). The short version:

- Google refuses OAuth in embedded user-agents, so authorization happens in the **system
  browser**, not an Electron `BrowserWindow`.
- GitHub gained PKCE (S256) in July 2025 but still does not distinguish public from
  confidential clients, so a secret-free desktop flow can't be assumed there.
- One backend-mediated flow therefore covers both, and a third provider is backend-only work.

```text
app → system browser → /api/v2/auth/{provider}/start
                            ↓ PKCE S256 + state, stored server-side
                       provider consent
                            ↓
                       backend callback → verify state → exchange code
                            ↓
                       mint app JWT + rotating refresh token
                            ↓
                       127.0.0.1:<ephemeral>/callback?code=<one-time>
                            ↓
                       app exchanges it, stores refresh token in the OS keychain
                       (Electron safeStorage — never localStorage, never plaintext)
```

Supporting tables: `oauth_state(state PK, provider, code_verifier, created_at, expires_at)` and
`refresh_token(id, user_id, token_hash, issued_at, expires_at, rotated_from, revoked_at)`.
Store the hash, never the token.

**Identity is keyed on `(provider, provider_subject)`, never on email.** Do not auto-link a
Google and a GitHub identity because their emails match — that is a known pre-account-takeover
path. Linking a second provider is an explicit action taken while already signed in.

---

## 3. Categorization

### Approach: hybrid, LLM-first for the backfill

Pure embeddings are the cheap answer but can't work yet: 2,623 links over 567 tags averages 4.6
examples per tag and is heavily skewed — the top tag has 124, the long tail has one or two.
Nearest-centroid over one example is noise.

So: **LLM for the 7,655-bookmark backfill** — one pass, batched, a small model, constrained to the
existing vocabulary with alias resolution — which brings every tag up to a usable number of
examples. **Then embeddings for steady state**: instant suggestions on save, no network round
trip, no per-save cost, with the LLM as fallback when the top candidate is below a confidence
floor or the page warrants a genuinely new tag.

Budget the backfill: 7,655 pages × ~2k tokens of extracted text. On a small model that's tens of
dollars, once — worth planning for rather than discovering.

### Pipeline

```text
save → normalise url → fetch page → extract text
                                      ├─ embed → cosine vs tag centroids → candidates ≥ τ
                                      └─ if best < τ or text is novel → LLM pass
                                                                          ↓
                                            resolve through tag_alias → dedupe → persist
                                            with source='ai', confidence=score
```

`tag_centroid(tag_id, embedding, n_samples, updated_at)` is the mean of member embeddings,
recomputed on a schedule. Cheap, and it makes steady-state suggestions free.

### Fixes to the current implementation

- **Ask for JSON and parse JSON.** Use structured output rather than splitting on `'. '`. This
  alone makes the existing feature start working.
- **Constrain to the vocabulary, but allow proposals.** Return `{"tags": [...], "proposed": [...]}`
  where `tags` must come from the supplied list. Proposed tags go to a review queue, not straight
  into `tag` — otherwise the vocabulary degrades exactly as it already has.
- **Resolve through `tag_alias` before insert**, replacing the hardcoded `corrections` dict.
- **Store confidence** so the browser can show suggestions as provisional chips.
- **Fix the fetch.** Drop `verify=False`, set a real User-Agent, cap response size, honour
  timeouts, and move it out of the request path — a save must not block on a slow third-party
  site. `BackgroundTasks` to start; `arq` or Celery when it hurts.

---

## 4. API v2

Versioned at `/api/v2/*` alongside the existing routes, so the extensions keep working while
they migrate.

```text
POST   /api/v2/auth/{provider}/start                → 302 to provider (google | github)
GET    /api/v2/auth/{provider}/callback             → 302 to loopback with one-time code
POST   /api/v2/auth/exchange        {code}          → {access_token, refresh_token, user}
POST   /api/v2/auth/refresh         {refresh_token} → rotated pair
POST   /api/v2/auth/logout          {refresh_token} → 204, revokes the chain
GET    /api/v2/me                                   → the signed-in user + linked identities
POST   /api/v2/me/identities/{provider}             → link a second provider (signed in only)

POST   /api/v2/bookmarks            {url, title?, saved_from?, tags?[]}  → 200 existing | 201 created
GET    /api/v2/bookmarks            ?tag=&tags=a,b&mode=all|any&site=&q=&since=&limit=&cursor=
GET    /api/v2/bookmarks/{id}
PATCH  /api/v2/bookmarks/{id}
DELETE /api/v2/bookmarks/{id}       (soft)
POST   /api/v2/bookmarks/{id}/tags  {tags:[...], source}
DELETE /api/v2/bookmarks/{id}/tags/{tag}
POST   /api/v2/bookmarks/{id}/suggest-tags          → {suggestions:[{tag,confidence}], proposed:[]}
GET    /api/v2/tags                 ?q=&min_count=  → with usage counts
POST   /api/v2/tags/{id}/merge      {into}          → the alias operation, exposed
GET    /api/v2/search               ?q=  (full-text + vector, hybrid)
```

Every bookmark route is scoped to the signed-in user. `GET /bookmarks` returns *your* saves;
the shared `bookmark` table is never addressable directly.

`POST /bookmarks` is **idempotent on `url_hash`** — what makes "save this page" safe to hit twice,
and the direct fix for 2,216 duplicates. It returns the existing bookmark with its tags so the
browser can immediately show what it already knows about the page.

**Auth:** all writes require a bearer token. Two kinds are accepted: the short-lived access JWT
issued by the OAuth flow (the browser), and long-lived per-client API tokens bound to a user
(the extensions, which cannot run an interactive sign-in). Both resolve to an `app_user`, so
handlers see a user either way.

The extensions currently post with no credentials at all — closing that is M0's job, before
anything else here is built.
