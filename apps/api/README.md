# bookmarks-api (v2)

FastAPI service for Smart-Browser. Mounted at `/api/v2` so it runs alongside the existing
v1 app — the Chrome and Firefox extensions keep posting to `/xyzzy` until M6 retires it.

## Status

Runs against a **new database** built from the target schema (ADR 0006), not the v1
`bookmarks-pg` tables. There is no data in it until the importer at M2.

What it gives you:

- **Authentication on every request**, reads included. Bookmarks belong to a user, so
  there is no coherent anonymous read. With no tokens configured the API refuses
  everything rather than allowing it.
- **Saving cannot duplicate.** `UNIQUE (url_hash)` plus `INSERT ... ON CONFLICT DO
  NOTHING`: 201 the first time, 200 every time after, never a second row — whatever the
  URL's spelling and however many clients call at once. The database arbitrates, not this
  code.
- **`GET /bookmarks/lookup`** answers "have I saved this?" without writing.
- **Tag intersection** — `?tags=python,fastapi&mode=all` — and `?untagged=true`.
- **Per-user isolation.** Every read joins through `user_bookmark` filtered by `user_id`.

## Tests

```sh
make -C ../.. test      # 66 API tests + 9 for the version script, no infrastructure
```

The default suite runs against **SQLite in memory** — no Docker, no database to start, no
skips. Everything in `models.py` is plain SQLAlchemy, so the schema builds and the real route
logic (idempotency, tag intersection, auth) is exercised.

The Postgres suite covers what SQLite structurally cannot — sequence detection, advisory-lock
id allocation, and a full `alembic upgrade head` / `downgrade base` round trip against a
v1-shaped schema:

```sh
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5436/bookmarks_test \
  make -C ../.. test-pg
```

**Never point `TEST_DATABASE_URL` at the real bookmarks database** — that suite creates and
drops tables.

A suite that is skipped by default is a suite that rots, which is why the fast one is the
default and the slow one is opt-in rather than conditional on an environment variable being
present.

Warnings are errors (`filterwarnings = ["error", ...]`), because the release checklist
requires a clean run. The third-party deprecations we cannot fix are listed explicitly.

## Migrations

Alembic, in `migrations/`. Revision `0001` creates the whole schema on an empty database.

```sh
make -C ../.. migrate-status   # what the database is at vs what the code wants
make -C ../.. migrate          # bring it to head
```

Before the first migration, confirm the server and your privileges:

```sql
SELECT version();          -- target schema needs PG 12+; M3 needs pgvector 0.5+
SELECT current_user, session_user;
\dt                        -- the Owner column must be you, or you must be superuser
```

The database starts empty. `make migrate` creates every table from scratch, so there is no
hand-applied state to reconcile and nothing to stamp.

## Compatibility checks

Version numbers label releases; these two enforce that things actually fit together. See
`doc/decisions/0005-versioning-and-compatibility.md`.

**API → database.** At startup, `schema_guard.verify()` compares the database's Alembic
revision against `REQUIRED_SCHEMA_REVISION` and refuses to boot on a mismatch — in either
direction, because a database *ahead* of the code is as dangerous as one behind. The error
names both revisions and the command to fix it.

This turns the worst failure in the system — code expecting a column that is not there,
surfacing at 2am as a 500 on one endpoint — into a process that will not start.
`SCHEMA_CHECK=false` exists for the case where you knowingly need to bypass it. It is not
something to set by default, and not a way to ship a release.

Adding a migration means bumping `REQUIRED_SCHEMA_REVISION`. A test asserts it equals the
Alembic head, so forgetting fails the build rather than the deployment.

**Browser → API.** `/api/v2/health` reports `contract` (the `v2`, which moves only on a
breaking change) separately from `version` (the release label, which moves every deploy).
The browser asserts `contract` at startup from M5, so a mismatch reads as "this version of
Smart-Browser needs a newer server" rather than a mysterious 404.

## Layout

```text
src/bookmarks_api/
├── config.py      settings; the embedding dimension lives here, not in code
├── db.py          engine + session
├── deps.py        bearer auth, and the current_user seam
├── schema_guard.py  refuses to start against a mismatched database
├── models.py      the target schema: bookmark / user_bookmark / tag
├── schemas.py     the v2 contract
├── urlnorm.py     normalisation + hashing; the dedupe foundation
└── routers/
```

`BookmarkOut.id` is the id of *your save* (`user_bookmark`), not of the shared `bookmark`
row. Clients address their own saves and never the global URL record — which is what keeps
one person's library invisible to another.

## Known limitations

Deliberate, and tracked in `doc/plan.md`:

- **No sign-in.** A static API token maps to an `app_user` row created on first use. M1
  replaces that with OAuth through `user_identity`; every handler already takes an
  `AppUser`, so only `deps.py` changes.
- **No content, no embeddings, no AI tags.** `bookmark_content` and `tag_centroid` arrive
  at M3 with the crawler that fills them — they are the only tables needing pgvector.
- **No data.** The importer from the cleaned-up `bookmarks-pg` is M2.
- **`source` on tag links is stored but nothing sets it to `ai` yet.** The column is there
  so M4 needs no migration, and so the UI can distinguish suggestions from choices.
