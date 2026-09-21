# bookmarks-api

FastAPI service for Smart-Browser. The API is versioned in its path (`/api/v1`) so a
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
cp .env.example ../../.env            # or apps/api/.env; both are read

make -C ../.. api-install             # uv sync
make -C ../.. migrate                 # creates the schema
make -C ../.. api-dev                 # http://127.0.0.1:8000/api/v1/docs
```

Dependencies are managed with [uv](https://docs.astral.sh/uv/). `uv.lock` is committed and
is what CI installs (`--frozen`, so a lockfile out of step with `pyproject.toml` fails the
build rather than quietly resolving something else). Dev tools live in a PEP 735
`[dependency-groups]` rather than an optional extra, so plain `uv sync` installs them.

`uv run` syncs before it runs, so every `make` target works from a clean checkout without
an install step — `make api-install` exists for when you want the sync on its own.

Generate a token:

```sh
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Configuration

Two `.env` files are read, both by absolute path so it makes no difference which
directory you run from — `alembic -c db/alembic.ini` from the repo root picks up
exactly what `make migrate` does:

| File | For |
| --- | --- |
| `<repo root>/.env` | Project-wide values shared by everything in the monorepo |
| `apps/api/.env` | API-specific overrides. Optional |

Later wins, so `apps/api/.env` overrides the root. Real environment variables beat both.
A single root `.env` is usually all you want; `apps/api/.env.example` is the template for
the API's share of it.

Both are gitignored. They hold a password — keep it that way.

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

### Which database am I actually talking to?

```sh
make -C ../.. db-doctor
```

It prints which `.env` files were found, any `DB_*` set in the environment (which beat
both files), where the package was imported from, what the settings resolve to, and then
asks the server it reaches to identify itself — including `data_directory`, the one
fingerprint no two running instances can share.

Worth running whenever a migration reports success and the tables are not where you
expect. With several Postgres instances on one machine, each can hold a database of the
same name owned by a role of the same name, and neither psql nor alembic will mention it.

Note that `\d` in psql only lists relations in your session's `search_path`. `\dt *.*`
ignores it and is the honest check.

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

Or directly: `uv run pytest` from `apps/api`.

The default suite runs against **SQLite in memory** — no Docker, no database to start, no
skips. Everything in `models.py` is plain SQLAlchemy, so the schema builds and the real
route logic (idempotency, tag intersection, auth, per-user scoping) is exercised.

The Postgres suite covers what SQLite structurally cannot: that `alembic upgrade head`
builds the schema the models describe, and that `UNIQUE (url_hash)` is what rejects a
duplicate rather than the application being careful.

```sh
createdb page_history_test -O api                     # once
make -C ../.. db-bootstrap DB=page_history_test       # once: pgvector, as a superuser
make -C ../.. test-pg
```

The extension is per database, so the test database needs its own bootstrap. Revision
`0002` stops with that exact command if it is missing.

`test-pg` builds the URL from `.env`, swapping `DB_NAME` for `<DB_NAME>_test`, and reads
the password in the shell — so it never reaches your command line or your shell history.
`TEST_DATABASE_URL` overrides it, and either way the target **refuses a URL pointing at
the configured database**: this suite creates and drops tables, and checking only that the
variable was set is not a guard.

A suite that is skipped by default is a suite that rots, which is why the fast one is the
default and the slow one is opt-in rather than conditional on an environment variable
happening to be set.

Warnings are errors (`filterwarnings = ["error", ...]`), because the release checklist
requires a clean run. The third-party deprecations we cannot fix are listed explicitly.

## Migrations

Alembic, in `db/migrations/` at the repo root — the schema belongs to the project, not to
this service, and **migrating it does not require this package**. `db/` has its own
`pyproject.toml` needing only alembic, sqlalchemy and psycopg:

```sh
cd db && uv run alembic upgrade head        # or, from the repo root:
make migrate
```

`env.py` resolves the database URL itself, via `db/migrations/dburl.py`, reading the same
`.env` files with the same precedence using nothing but the standard library. The API
package is imported only for `--autogenerate`, and only if it happens to be installed.

`alembic -x db_url=postgresql+psycopg://…` overrides everything, for a scratch database or
a recovery.

That does mean the URL is built in two places. `apps/api/tests/test_dburl.py` builds both
from identical inputs and asserts they agree, including their defaults.

**The DDL is SQL, not Python.** It lives one object per file in `db/schema/create/`, with
`create_tables.sql` as the ordered manifest. Revision `0001` parses that manifest and runs
each file it names, so there is one ordering rather than two that can drift:

```text
db/schema/
├── create/
│   ├── create_tables.sql   ordered manifest: \echo + \ir, runnable under psql
│   ├── tag_source.sql      the enum, first — the tables depend on it
│   ├── app_user.sql
│   └── …
└── drop/
    └── drop_tables.sql     reverse order, used by the downgrade
```

It runs under psql directly, which is the point of keeping it as SQL:

```sh
psql "$DATABASE_URL" -f db/schema/create/create_tables.sql
```

`\ir` rather than `\i`: `\i` resolves relative to psql's working directory, `\ir`
relative to the file doing the including. The difference is whether running it from the
repo root works.

Two deliberate departures from the convention used elsewhere. The create files carry **no
`DROP TABLE IF EXISTS`** — idempotent rebuild is right when building from nothing and is
silent data loss on a migration's upgrade path, so drops live in `schema/drop/`. And the
revision **refuses** any psql meta-command it does not implement rather than skipping it,
because a skipped meta-command is DDL silently not run.

### Two sources of truth

The schema is now stated twice: in these SQL files and in `models.py`. Both earn their
place — the SQL is what runs against Postgres, the models are what the ORM and the SQLite
test suite use — but two sources drift. `test_sql_files_and_models_describe_the_same_schema`
in the Postgres suite builds both and diffs columns, types, nullability, defaults, primary
keys, unique constraints and foreign keys.

It earned its keep immediately: `is_active`, `visit_count` and `source` had Python-side
defaults in the models and server defaults in the SQL. A Python default only applies when
the ORM does the insert, so raw SQL and `INSERT ... ON CONFLICT` would have written NULL
into NOT NULL columns.

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

**Browser → API.** `/api/v1/health` reports `contract` (which moves only on a breaking
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
├── urlnorm.py       normalisation + hashing; the dedupe foundation (ADR 0011)
├── rehash.py        rekeys existing rows after a urlnorm change: make rehash-urls
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
