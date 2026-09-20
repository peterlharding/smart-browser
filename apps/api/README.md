# bookmarks-api

FastAPI service for Smart-Browser. The API is versioned in its path (`/api/v2`) so a
breaking change need not break installed clients — an extension updates on its own
schedule, not the server's.

## Status

Runs against its own database, `page_history`. There is no data in it: nothing imports
the predecessor's bookmarks, by design (ADR 0007).

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

## Quick start

```sh
createdb page_history -O api          # its own database, owned by the role that will use it
cp .env.example .env                  # then set DB_USER, DB_PASSWORD, API_TOKENS

make -C ../.. api-install
make -C ../.. migrate                 # creates the schema
make -C ../.. api-dev                 # http://127.0.0.1:8000/api/v2/docs
```

Generate a token:

```sh
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Configuration

Everything lives in **`apps/api/.env`** — copy `.env.example`. It is read relative to that
directory, not to wherever you started the process, so `alembic -c apps/api/alembic.ini`
run from the repo root picks up the same settings as `make migrate`. Real environment
variables override the file.

| Variable | Notes |
| --- | --- |
| `DB_HOST`, `DB_PORT` | Default `127.0.0.1:5432` |
| `DB_NAME` | `page_history` |
| `DB_USER`, `DB_PASSWORD` | **Required** — see below |
| `API_TOKENS` | `name:token` pairs, or a bare token |
| `SINGLE_USER_ID` | The user a bare token acts as |
| `SCHEMA_CHECK` | `false` bypasses the startup revision check. Not a default |
| `EMBEDDING_*` | M3; the dimension is a config value so it can be benchmarked |

`API_TOKENS` takes `name:token` pairs, so more than one client can act as more than one
user before OAuth lands:

```sh
API_TOKENS=plh:s3cret,alice:t0ken     # two users
API_TOKENS=s3cret                     # one user, named by SINGLE_USER_ID
```

## Roles and table ownership

`DB_USER` is not optional, and the API refuses to build a connection URL without it.

Left empty, libpq treats the user as unset and falls back to the **operating-system**
user. Postgres assigns table ownership to whoever runs `CREATE TABLE`, so a migration run
that way leaves every table owned by the wrong role — and it *succeeds*, which is exactly
why it is worth failing loudly instead.

Owning the database is not the same as owning its tables. `createdb page_history -O api`
makes `api` the database owner; tables still belong to whichever role created them.

Alembic prints both before any DDL runs:

```text
[alembic] connected to 'page_history' as 'api'
```

### Fixing ownership after the fact

If the database has no data worth keeping — which it will not, early on — start again as
the right role:

```sh
dropdb page_history
createdb page_history -O api
# set DB_USER=api in apps/api/.env
make -C ../.. migrate
```

To keep what is there, reassign in place. Run this **connected to `page_history`**:
`REASSIGN OWNED` acts on the current database, so connecting elsewhere moves the wrong
objects.

```sql
\c page_history
REASSIGN OWNED BY plh TO api;
```

If `plh` owns other things in that database you want left alone, be explicit instead.
Sequences and the enum type are separate objects and are missed by table-only changes:

```sql
\c page_history
ALTER TABLE app_user OWNER TO api;
ALTER TABLE user_identity OWNER TO api;
ALTER TABLE bookmark OWNER TO api;
ALTER TABLE user_bookmark OWNER TO api;
ALTER TABLE tag OWNER TO api;
ALTER TABLE tag_alias OWNER TO api;
ALTER TABLE bookmark_tag OWNER TO api;
ALTER TABLE alembic_version OWNER TO api;
ALTER TYPE tag_source OWNER TO api;

DO $$ DECLARE s text;
BEGIN
  FOR s IN SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'
  LOOP EXECUTE format('ALTER SEQUENCE public.%I OWNER TO api', s); END LOOP;
END $$;
```

Check with `\dt`, `\ds` and `\dT` — the Owner column should read `api` throughout.

## Tests

```sh
make -C ../.. test      # 97 API + 41 extension + 12 tooling, no infrastructure
```

The default suite runs against **SQLite in memory** — no Docker, no database to start, no
skips. Everything in `models.py` is plain SQLAlchemy, so the schema builds and the real
route logic (idempotency, tag intersection, auth, per-user scoping) is exercised.

The Postgres suite covers what SQLite structurally cannot: that `alembic upgrade head`
builds the schema the models describe, and that `UNIQUE (url_hash)` is what rejects a
duplicate rather than the application being careful.

```sh
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/page_history_test \
  make -C ../.. test-pg
```

**Never point `TEST_DATABASE_URL` at a database you care about** — that suite creates and
drops tables.

A suite that is skipped by default is a suite that rots, which is why the fast one is the
default and the slow one is opt-in rather than conditional on an environment variable
happening to be set.

Warnings are errors (`filterwarnings = ["error", ...]`), because the release checklist
requires a clean run. The third-party deprecations we cannot fix are listed explicitly.

## Migrations

Alembic, in `migrations/`. Revision `0001` creates the whole schema on an empty database.

```sh
make -C ../.. migrate-status   # what the database is at vs what the code wants
make -C ../.. migrate          # bring it to head
```

The models are the source of truth, so `alembic revision --autogenerate` works. Review
what it produces: it is reliable for tables and columns, and blind to server defaults,
enum changes and anything needing a data migration.

## Compatibility checks

Version numbers label releases; these two enforce that things actually fit together. See
`doc/decisions/0005-versioning-and-compatibility.md`.

**API → database.** At startup, `schema_guard.verify()` compares the database's Alembic
revision against `REQUIRED_SCHEMA_REVISION` and refuses to boot on a mismatch — in either
direction, because a database *ahead* of the code is as dangerous as one behind. The error
names the database, host and port, since being pointed at the wrong one is the commonest
cause.

Adding a migration means bumping `REQUIRED_SCHEMA_REVISION`. A test asserts it equals the
Alembic head, so forgetting fails the build rather than the deployment.

**Browser → API.** `/api/v2/health` reports `contract` (which moves only on a breaking
change) separately from `version` (the release label, which moves every deploy). The
browser asserts `contract` at startup from M5.

## Layout

```text
src/bookmarks_api/
├── config.py        settings; .env anchored to this directory, not to cwd
├── db.py            lazy engine + session
├── deps.py          bearer auth, token -> app_user
├── models.py        the schema: bookmark / user_bookmark / tag
├── schemas.py       the v2 contract
├── schema_guard.py  refuses to start against a mismatched database
├── urlnorm.py       normalisation + hashing; the dedupe foundation
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
- **No data.** Nothing imports the predecessor's bookmarks (ADR 0007).
- **`source` on tag links is stored but nothing sets it to `ai` yet.** The column exists so
  M4 needs no migration, and so the UI can distinguish suggestions from choices.
