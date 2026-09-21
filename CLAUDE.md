# Smart-Browser — working notes for Claude Code

A browser wrapping the Chrome engine where bookmarks behave like tags: one save, many
categories, with AI categorisation over the corpus. It is an API, a Chrome extension, and
the first slice of the Electron browser (M5, ADR 0015).

Read [`doc/plan.md`](doc/plan.md) first — it says what is done, what is next, and what is
still an open question. Decisions live in [`doc/decisions/`](doc/decisions/) as ADRs;
rationale in [`doc/architecture.md`](doc/architecture.md).

## Hard rules

- **Never touch `bookmarks-pg`.** The predecessor project at
  `/Volumes/u/src/wip/bookmarks/bookmarks-pg` continues as it is. Do not read it unless
  asked, and never write to it. Nothing here explains itself by reference to it (ADR 0007).
- **`uv` for all Python.** `uv sync`, `uv run`, `uv add` — never bare `pip` or `python`.
  `apps/api` and `db` are separate projects with separate lockfiles.
- **Never put `DB_PASSWORD` in a make variable.** Make echoes recipes with values already
  substituted, into the terminal and the scrollback. Recipes read it in the shell instead.
- **`TEST_DATABASE_URL` must never name the real database.** The Postgres suite creates
  and drops tables; `make test-pg` refuses the configured database and derives a
  `<DB_NAME>_test` URL itself.
- **No `DROP` in `db/schema/create/`.** A drop on the upgrade path is silent data loss
  when a migration re-runs. Drops live in `db/schema/drop/`.

## Commands

```sh
make check          # everything the release checklist requires
make test           # API (SQLite) + scripts + extension — no infrastructure
make test-pg        # Postgres suite; derives its own URL from .env
make api-lint       # ruff + mypy
make migrate        # alembic upgrade head
make db-bootstrap   # CREATE EXTENSION vector, as a superuser; once per database
                    # and the test one too: make db-bootstrap DB=page_history_test
make db-doctor      # which database, as whom, which revision, which tables
make rehash-urls    # after any urlnorm.py change; CONFIRM=yes to apply
make worker         # the crawl worker; ONCE=yes drains what is due and exits
make embed          # the embedding pass; ONCE=yes embeds what is waiting and exits
make test-model     # the real embedding model; downloads 64 MB once
make browser-dev    # build and run the browser
make browser-check  # the browser's type checks and unit tests (part of make check)
make test-browser-e2e  # the built browser against the real API on <DB_NAME>_test
make crawl-status   # jobs by state, latest errors
make schema-drop CONFIRM=yes
```

## Layout

```text
apps/api/          FastAPI + SQLAlchemy 2.0 + psycopg 3.  Its own uv project.
apps/extension/    MV3 Chrome extension.  Plain JS, node --test, no build step.
apps/browser/      Electron shell (M5, ADR 0015). TypeScript, Svelte, Vite + esbuild.
                   An npm workspace: `make browser-install` once.
db/                alembic.ini, migrations/, schema/.  Its own uv project: migrating
                   needs alembic and psycopg, not the API package.
doc/               plan, architecture, ADRs, NOTES.
packages/shared-types/openapi.json   generated; `make api-openapi`.
```

## Schema conventions

- **The DDL is SQL files**, one per object, in `db/schema/create/`. Each Alembic revision
  has **its own manifest** — `create_tables.sql` is `0001`, `create_content.sql` is
  `0002`, `create_saved_title.sql` is `0003` — and the revision executes the files its
  manifest names (`db/migrations/sqlrunner.py`). Manifests are never nested: the runner
  would execute a file of meta-commands and silently do nothing. A test insists every
  create file is named by exactly one manifest.
- **Never edit a file an earlier revision runs.** Revision `0001` executes
  `user_bookmark.sql` as it is *now*, so a new column is a new file
  (`user_bookmark_saved_title.sql`) in a new revision, with its reverse in `schema/drop/`.
- Keys are `bigint GENERATED ALWAYS AS IDENTITY`; foreign keys are `bigint`. `ALWAYS`,
  not `BY DEFAULT`: an explicit id written past the sequence collides later, long after
  whatever wrote it is forgotten. `OVERRIDING SYSTEM VALUE` is the deliberate escape hatch.
- **Enums are created idempotently** and verify their labels — Postgres has no
  `CREATE TYPE IF NOT EXISTS`, and a type survives dropping the tables that use it.
  Tables are deliberately *not* idempotent: `IF NOT EXISTS` would accept a
  differently-shaped table and hide real drift.
- **The schema is stated twice** — the SQL files and `models.py` — and a Postgres test
  diffs them (columns, types, nullability, defaults, identity, enum labels, keys). Change
  one, change the other, or that test fails. `bookmark_content.tsv` is the single listed
  exception.
- **URL normalisation merges only spellings of the same resource** (ADR 0011). Its output
  is the identity *and* the stored link, so a rule that merges pages which only usually
  match rewrites someone's link and loses a page for good. No trailing-slash stripping, no
  query sorting, no re-encoding; http and https only. Any change to `urlnorm.py`,
  including a new tracking parameter, needs `make rehash-urls` on existing databases.
- `bookmark` is the URL; `user_bookmark` is one person's save. Crawl and embed cost is
  per-URL, never per-user-per-URL (ADR 0001).
- `UNIQUE (url_hash)` is the entire no-duplicates guarantee. `POST /bookmarks` is an
  upsert: 201 then 200, never a second row, whatever the client does.

## Testing

Three suites, and the standing lesson from this project: **a test that cannot reach the
failure is not evidence.**

- **Default** (`make test-api`): SQLite in memory. Fast, no skips.
- **Postgres** (`make test-pg`): opt-in, `-m postgres`. Covers what SQLite cannot —
  migrations, `GENERATED ALWAYS`, the schema diff, real unique violations. It sat unrun
  for days and found real bugs the hour it first ran; run it before claiming a schema
  change works. The test role needs neither SUPERUSER nor CREATEDB, deliberately, and
  `test_the_schema_needs_no_special_privileges` holds the schema to that even when the
  suite connects as a superuser, as CI does. Keep it first in its module, and keep
  `test_migration_pg.py` sorting before any other Postgres module.
- **Browser** (`make browser-check`, `make test-browser-e2e`): Vitest for the logic, and
  Playwright driving the built app against the real API and a local site, with snapshots
  of every layer in `apps/browser/test-results/snapshots/` to look at, not only assert on.
  The UI, the tabs and the overlay are separate views of one window: Playwright sees each
  as a page, and a detached view's page is gone, so fetch the overlay afresh after it opens.
  Playwright's Electron launch changes the app under test, silently: its loader appends
  `--password-store=basic` and `--use-mock-keychain` with `appendSwitch`, overriding any
  switch you pass (on Linux that means no encryption, so the browser refuses its token;
  `test/e2e/linux-secret-store.cjs` undoes it), and it adds `--no-sandbox` on Linux unless
  `chromiumSandbox: true`. Chromium switches go before the app path; after it, Electron
  hands them to the app. When CI and a bare `electron` disagree, suspect the harness.
- **Extension** (`make test-ext`): `node --test`, no dependencies. Node's `fetch` does not
  check its receiver and Chrome's does, so the suite carries a stand-in that is as strict
  as the browser. Keep it that way.

When a bug turns out to be invisible to the suite, fix the suite in the same commit and
say so — that is where most of this project's real defects have lived.

## Conventions

- **CHANGELOG entries are written with the change**, under `## [Unreleased]`, not at
  release time. `RELEASING.md` has the workflow; `scripts/version.py` moves the versions.
- **A decision gets an ADR.** Numbered, dated, with the options that lost and why.
  History is not rewritten: superseded ADRs stay as they were.
- **Commit messages say what failed and why the fix is right**, not just what changed.
- `/api/v1` is the contract path and `API_CONTRACT_VERSION` matches it (ADR 0008).
  `REQUIRED_SCHEMA_REVISION` in `schema_guard.py` moves with each migration; the API
  refuses to start against a database that is not at it.
- Auth is a declared `HTTPBearer` scheme, so `/api/v1/docs` has an Authorize dialog.
  Tokens come from `API_TOKENS` as `name:token` pairs. With none set, the API refuses
  everything — an unconfigured deployment should be inert, not public.

## Current state

M0 and M3 are done. Revision `0002` added `bookmark_content` and `crawl_job`, the save
path enqueues inside its own transaction (ADR 0009), the crawl worker drains it (ADR 0012:
`make worker`, `make crawl-backfill`, `make crawl-status`), and a separate embedding pass
turns its text into vectors (ADR 0013: `make embed`). `fetch.py` is the only module that
touches the network and `embedder.FastembedModel` the only one that loads the model; both
are parameters, so tests use fakes. The real model is `make test-model`, opt-in and run in
CI. **Next: M4**, blocked on the open questions in `doc/plan.md` (which LLM, tag
hierarchy).

Titles (ADR 0010, revision `0003`): `title_override` is what you typed (PATCH only),
`user_bookmark.saved_title` is what the client saw (POST), `bookmark.title` is what the
crawler fetched, displayed in that order. The worker writes `bookmark.title` and nothing
else about titles.

M1 (OAuth) is deferred behind M3: it replaces a working bearer token for one user, and it
needs a deployment that can receive a callback. This runs locally for now.
