# bookmarks-api (v2)

FastAPI service for Smart-Browser. Mounted at `/api/v2` so it runs alongside the existing
v1 app — the Chrome and Firefox extensions keep posting to `/xyzzy` until M6 retires it.

## Status: M0

This talks to the **existing** database schema (`bookmark` / `tag` / `bookmark_tag` as they
are today). It does not migrate anything. M2 changes the schema; see `doc/architecture.md`
for the target and `doc/plan.md` for sequencing.

What M0 delivers over the v1 endpoints:

- **Authentication on every write.** `/xyzzy` has none today.
- **Idempotent save.** `POST /bookmarks` matches an existing URL and returns 200 rather
  than creating a duplicate row. 23% of the current corpus is duplicates.
- **Race-free id allocation.** `SELECT MAX(id)+1` is replaced by real sequences
  (Alembic revision `0001`); until that is applied, an advisory lock serialises
  allocation as a fallback.
- **URL normalisation** with a test suite, which is the foundation of M2's dedupe.
- **Tag intersection queries** — `?tags=python,fastapi&mode=all` — with the indexes to
  make them fast.

## Quick start

```bash
cp .env.example .env      # fill in DB_USER, DB_PASSWORD, API_TOKENS
make -C ../.. api-install
make -C ../.. api-test
make -C ../.. api-dev     # http://127.0.0.1:8000/api/v2/docs
```

Generate a token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

With `API_TOKENS` unset, writes return **503**, not 200. An unconfigured deployment should
be inert rather than open — that failure mode is how `/xyzzy` ended up world-writable.

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

Alembic, in `migrations/`. The DDL lives in `migrations/sql/*.sql` and the revision reads
it — so the statements stay reviewable as SQL, `psql -f` still works in an emergency, and
there is one copy of them rather than two.

Revision `0001` is additive only: no column is dropped, renamed or retyped, and no
constraint is added that current data would violate. The v1 app keeps working with it
applied.

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

Run migrations as the **table owner** (`plh`) or a superuser: `CREATE SEQUENCE ... OWNED BY`
and `ALTER TABLE ... SET DEFAULT` both require ownership, and an unprivileged role fails
partway with the sequences created but not attached. Everything is `IF NOT EXISTS`, so
re-running as the owner recovers cleanly.

**The live database has never been stamped by Alembic.** The first run is one of:

```sh
make -C ../.. migrate                  # applies 0001 and stamps it
make -C ../.. migrate-stamp REV=0001   # if the SQL was already applied by hand
```

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
├── ids.py         advisory-lock id allocation (dead once 0001 is applied)
├── schema_guard.py  refuses to start against a mismatched database
├── models.py      SQLAlchemy over the *current* schema
├── schemas.py     the v2 contract — target field names over v1 storage
├── urlnorm.py     normalisation + hashing; the dedupe foundation
└── routers/
```

`schemas.py` deliberately uses the **target** field names (`created_at`, `saved_from`,
`site`) rather than the current column names (`used`, `host`, none). M2 changes the storage
underneath without changing the contract that the browser and extensions are written against.

## Known M0 limitations

These are deliberate and tracked in `doc/plan.md`:

- `DELETE /bookmarks/{id}` is a **hard delete**. `deleted_at` arrives in M2; don't wire a
  one-keystroke delete to it yet.
- `?site=` is a `LIKE` over the URL, not an indexed lookup — `site` is derived, not stored,
  until M2.
- `source` on `POST /bookmarks/{id}/tags` is accepted and discarded; the column arrives in
  M2. It is in the contract now so nothing needs changing when it lands.
- Tags are capped at 32 characters because the current column is `varchar(32)`. Longer tags
  are rejected with 422 rather than silently truncated. M2 widens it.
- Idempotency matches on the URL string, not `url_hash`. Two differently-spelled URLs for
  the same page still create two rows until M2's unique index.
- **Everything acts as one user.** The pre-migration schema has no ownership columns, so
  `current_user` returns the configured id. M1 adds `app_user`, OAuth sign-in and a real
  token lookup; because every handler already takes a user, none of them change.
