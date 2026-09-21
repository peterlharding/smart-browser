# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Add entries under `## [Unreleased]` as part of each change, not at release time.

## [Unreleased]

### Fixed

- **Tag names were not checked, and aliases resolved only when saving**
  ([ADR 0014](doc/decisions/0014-tag-names.md)). Each of these was reproduced against a
  running API first.
  - `red,green` could be saved and never filtered on, since `?tags=` splits on commas;
    names with spaces or tabs were saved too, though every client splits typed tags on
    whitespace. A tag name now contains no comma, whitespace or control character, on
    every write path, as a 422 naming the tag and the rule.
  - `?tags=boorstrap` found nothing and `DELETE .../tags/boorstrap` was a 404, though
    saving `boorstrap` stored `bootstrap`. Every path that names a tag resolves aliases,
    and in a `mode=all` filter an alias and its tag count once.
  - `PATCH` with an alias deleted the tag's link and re-added it as `source = user`,
    turning an AI suggestion into the person's own choice. It compares canonical names
    now, so the link and its source stay.
  - A tag containing `/` could be saved and never removed: the delete route stopped at the
    first slash. It matches the rest of the path now; the URL is unchanged.
- **The extension refused tags over 32 characters**, the retired schema's limit, which the
  server dropped in 0.2.0. And when a save is refused, the popup shows the server's own
  message instead of "The server could not accept that."

## [0.3.0] - 2026-09-21

See [release_notes/v0.3.0.md](release_notes/v0.3.0.md) for details.

### Added

- **The embedding pass** ([ADR 0013](doc/decisions/0013-embeddings.md)). `make embed`
  turns each crawled page's title, description and text into a 384-dimension vector with
  `bge-small-en-v1.5`, run through `fastembed`. Measured against `sentence-transformers`,
  it gave identical vectors at a fifth of the install size and a thirtieth of the load
  time. It runs as its own process, apart from the crawl worker; there is no queue table,
  because a page needs embedding whenever `bookmark_content.model` is not the current
  model and recipe, so changing either re-embeds everything with no migration. Batches of
  32 claimed with `SKIP LOCKED`, and the model's dimension checked against the column
  before anything is written. `make crawl-status` reports how many pages are embedded.
- **`make test-model`** runs the real model, which the default suite never downloads; CI
  runs it with the model cached.

### Removed

- The `EMBEDDING_BACKEND`, `EMBEDDING_DIM` and `OLLAMA_BASE_URL` settings, which nothing
  read. The dimension is the column's, fixed by `vector(384)` and checked by `make
  embed`. `EMBEDDING_MODEL` now names the model as `fastembed` does,
  `BAAI/bge-small-en-v1.5`, and `EMBEDDING_CACHE_DIR` says where it is downloaded. An
  `EMBEDDING_MODEL=bge-small-en-v1.5` copied from the old example `.env` is refused with
  a message naming the setting and the `BAAI/` prefix it lacks, rather than fastembed's
  own, which names neither.

### Documentation

- **`RELEASING.md` tags only after CI passes.** The steps had tagged and pushed the commit
  and the tag together, so 0.2.0's tag went out before CI failed on its commit. Push the
  release commit, wait for CI on it, then tag that exact commit; a tag on a bad commit is
  left alone and the next patch released, and a release body carries the notes of a
  version that was tagged but never published.

## [0.2.1] - 2026-09-21

See [release_notes/v0.2.1.md](release_notes/v0.2.1.md) for details.

### Fixed

- **0.2.0 was tagged with an OpenAPI contract that said 0.1.0.** The committed
  `packages/shared-types/openapi.json` embeds the release version, `make version-set`
  never regenerated it, and only CI compared it with what the app serves, so the release
  commit went red after the tag was pushed. `version-set` now regenerates it, and a new
  `make openapi-check`, part of `make check` and what CI runs, fails when it is stale.
  0.2.0 stays tagged and unpublished; 0.2.1 is the release.

## [0.2.0] - 2026-09-21

See [release_notes/v0.2.0.md](release_notes/v0.2.0.md) for details.

### Added

- **The crawl worker** ([ADR 0012](doc/decisions/0012-crawl-worker.md)). `make worker`
  drains `crawl_job` one page at a time: claim with `FOR UPDATE SKIP LOCKED` and a
  ten-minute lease, fetch with no transaction open, record the outcome. It fills
  `bookmark.title` (the lowest-ranked title, ADR 0010), `description`, `http_status`,
  `fetched_at` and `bookmark_content.text`, extracted with `trafilatura` so the text is
  the article rather than the navigation around it. Limits: 30 seconds, 5 redirects,
  5 MB, one request per host per second, HTML only. Loopback, link-local and
  private-network addresses are refused at every redirect unless `CRAWL_ALLOW_PRIVATE`.
  4xx fails at once with the status kept; 429, 5xx and network errors retry after 1, 4,
  16, 64 and 256 minutes, honouring `Retry-After` up to a day. `make crawl-backfill`
  queues pages saved before the queue existed; `make crawl-status` shows jobs by state
  and the latest errors.
- **Re-saving a page whose crawl failed revives the job.** A job that is ready, running
  or done is still left alone.

- **M3, first half: content and the crawl queue** (revision `0002`). `bookmark_content`
  holds extracted text, a generated `tsvector` and a 384-dimension embedding, keyed by
  URL so ten people saving a page pay for one fetch. `crawl_job` is the queue: keyed by
  `bookmark_id` so one outstanding crawl per URL is a database invariant, written in the
  same transaction as the bookmark so "saved but never queued" is unreachable. The worker
  that drains it is not here yet. [ADR 0009](doc/decisions/0009-crawl-queue-in-postgres.md)
- `make db-bootstrap` installs the `vector` extension as a superuser. pgvector is not a
  trusted extension, so the role that runs migrations cannot install it; revision `0002`
  checks for it and names this command rather than failing later on a missing type.
- `db/migrations/sqlrunner.py` — the manifest runner, shared by every revision instead of
  copied into each. Each revision has its own manifest: `create_tables.sql` is `0001`,
  `create_content.sql` is `0002`, and a test insists every create file is named by
  exactly one of them.

- **Bearer auth is declared as a security scheme**, so `/api/v2/docs` has an Authorize
  dialog and every protected operation shows a padlock. Reading the `Authorization`
  header by hand left FastAPI nothing to put in the OpenAPI document, and the docs page
  offered a bare header field instead — which invites `Bearer: <token>`, a 401.
- **Chrome extension** (`apps/extension/`): MV3, with a save sheet that shows existing tags
  and offers autocomplete ranked by your own usage. `⌘⇧B` to tag and save, `⌘⇧S` to quick
  save. Opening the popup is a lookup, never a write.
- `GET /api/v2/bookmarks/lookup` — read-before-write by URL.
- Soft delete on saves, with re-saving a deleted page restoring it rather than duplicating.
- `test_duplication.py` and `test_scoping.py` covering the two guarantees the schema buys.
- `scripts/version.py` now manages the extension's `package.json` and `manifest.json`,
  stripping the prerelease suffix for the manifest since Chrome rejects it.

### Changed

- **URL normalisation merges only spellings of the same resource**
  ([ADR 0011](doc/decisions/0011-conservative-url-normalisation.md)). Its output is both
  `url_hash` and the stored `bookmark.url`, the link you open and the crawler fetches, so
  every rule that merged pages which only *usually* match was rewriting links. It no
  longer strips a trailing slash (`/docs/` stays), sorts the query (`?a=2&a=1` kept an
  ordered list in the wrong order), re-encodes it (`?edit` became `?edit=`, `%20` became
  `+`, and a malformed escape was corrupted into U+FFFD), strips `campaign_id`, `trk`,
  `icid`, `scid`, `cmpid` or `ref_src` (generic names some sites use to select content),
  or drops hash routes (`#/settings` collapsed every page of an app to its root; routes
  starting `/` or `!` are now kept on every host, not three). Tracking parameters are cut
  from the query as written. Host casing, default ports, IDN to punycode and RFC 3986
  escape normalisation still merge. Only http and https are accepted: `chrome://`,
  `about:`, `file:` and the rest are a 422 naming the scheme, where `about:blank` used to
  fail with a message about a port.
- **`make rehash-urls`** rekeys existing rows after any change to the rules, the tracking
  list included. It reports rows whose new key another row holds instead of merging
  them, and rows the rules now reject instead of deleting them, and changes nothing
  without `CONFIRM=yes`. Run against the real database for this change: nothing to do.

- **The title seen at save time has its own column**, `user_bookmark.saved_title`
  (revision `0003`, [ADR 0010](doc/decisions/0010-title-seen-at-save.md)). The extension
  had been writing the tab title into `title_override`, which wins over everything, so
  the titles M3 is about to crawl would never have shown for anything saved from the
  extension, and a title you corrected was indistinguishable from one Chrome showed.
  `POST /bookmarks` `title` now writes `saved_title` and a re-save with a title refreshes
  it; `PATCH` `title` still writes `title_override`. Display is what you typed, then what
  you saw, then what was crawled: behind a login the crawler sees "Sign in", so the
  saved title outranks it. Existing overrides move to `saved_title`, since no client has
  ever let anyone type one. Request and response shapes are unchanged; contract `1`.
- **The API path is `/api/v1`, not `/api/v2`**, and `API_CONTRACT_VERSION` is `1`. The
  `2` was inherited from the predecessor, where it meant something; here it named a v1
  that never existed. One client, one constant and one generated contract file — the
  cheapest this will ever be. History is not rewritten: entries under `0.1.0` and
  `release_notes/` still say `/api/v2`, because that is what that release served. See
  [ADR 0008](doc/decisions/0008-api-path-v1.md).

- **Surrogate keys are `bigint GENERATED ALWAYS AS IDENTITY`**, replacing `SERIAL`
  integers. `ALWAYS` rather than `BY DEFAULT`: an explicit id written past the sequence
  leaves it behind the data, and the next generated value collides. The models mirror it
  with `Identity(always=True)` and a `with_variant(Integer, "sqlite")` so the SQLite test
  suite keeps auto-assigning — a `BIGINT` primary key is not a rowid alias there, and
  inserts omitting it would fail.
- **The schema is now explicit SQL**, one object per file in `db/schema/create/`, with
  `create_tables.sql` as the ordered manifest that both psql and the Alembic revision
  read — so the ordering exists once. `db/schema/drop/drop_tables.sql` is the downgrade.
  Create files carry no `DROP`, and the revision refuses any psql meta-command it cannot
  run rather than skipping it.
- Server defaults added to `is_active`, `visit_count` and `bookmark_tag.source`. They had
  Python-side defaults only, which apply when the ORM inserts and not when anything else
  does — including this API's own `INSERT ... ON CONFLICT` statements.

- **Python tooling moved to [uv](https://docs.astral.sh/uv/)**, matching how these
  projects are built elsewhere. `uv.lock` is committed and CI installs from it with
  `--frozen`, so a lockfile out of step with `pyproject.toml` fails the build instead of
  resolving something else. Dev tools moved from an optional extra to a PEP 735
  `[dependency-groups]`, which plain `uv sync` installs. Every `make` target now runs
  through `uv run`, which syncs first — so they work from a clean checkout.
- Added `make db-doctor`: prints which `.env` files were found, any `DB_*` shadowing them
  from the environment, where the package was imported from, what the settings resolve to,
  and what the server it reaches says about itself — database, role, listening port and
  `data_directory`. For when a migration reports success and the tables are not where you
  expect, which several Postgres instances on one machine makes easy.
- Added `make db-connect`, which reads `apps/api/.env` rather than hardcoding a host,
  port and role that now live in one place.
- **`DB_USER` is now required.** Left empty it built `postgresql+psycopg://:@…`, where
  libpq falls back to the operating-system user — so migrations connected as whoever ran
  them and, since Postgres assigns table ownership to whoever runs `CREATE TABLE`, left
  every table owned by the wrong role. It succeeded, which is what made it worth an
  exception. `database_url` now refuses to build without it and names the file to edit.
- **`.env` is read by absolute path**, not resolved against the working directory, so
  `alembic -c apps/api/alembic.ini` from the repo root no longer silently finds nothing
  and falls back to every default. Two files are read — `<repo root>/.env` for what the
  monorepo shares and `apps/api/.env` for API-specific overrides — with the latter
  winning and real environment variables beating both.
- Alembic prints the database and role it connected as before running any DDL.
- The engine is created on first use rather than at import, so importing the app no longer
  requires a working database configuration.
- **The database is now called `page_history`**, and the default connection points at a
  stock local Postgres on 5432. The previous defaults — port 5436, database `bookmarks` —
  were the predecessor's Docker instance and its database, so a default `make migrate`
  would have run DDL against a system this project has no business touching.
- Schema-guard errors now name the database, host and port they are talking about. Being
  pointed at the wrong database is the commonest cause of both of them, and a message that
  omits which database it means sends you to the migrations instead of the connection
  string.
- **Treated as a new implementation** rather than a successor (ADR 0007). The importer
  milestone and the `/xyzzy` retirement milestone are both out of scope: the predecessor
  will be brought into line with this project rather than the reverse, and nothing here
  explains itself by reference to a schema nobody will run again.
- `doc/audit-2026-09-20.md` is reframed as evidence about the problem — eleven years of a
  bookmarking system's measured failure modes — rather than a description of data being
  migrated. It stays unedited and stays load-bearing.
- **The API owns a clean database** rather than running against the v1 `bookmarks-pg`
  tables (ADR 0006). Revisions `0001` and `0002` are replaced by a single revision creating
  the target schema: identity, the `bookmark` / `user_bookmark` split, a global tag
  vocabulary with aliases, and tag links carrying provenance.
- **No-duplicates is now a database constraint.** `UNIQUE (url_hash)` plus
  `INSERT ... ON CONFLICT DO NOTHING` replaces check-then-insert, so saving the same page
  any number of times from any number of clients cannot produce a second row.
- **Reads require a token.** Bookmarks belong to a user, so an anonymous read has no
  coherent answer. `/health` remains open.
- `API_TOKENS` accepts `name:token` pairs, so more than one client can act as more than
  one user before OAuth lands.
- Tag names are no longer capped at 32 characters, and are no longer stored in `citext` —
  the application lowercases on every write path, so a plain `UNIQUE` suffices.

### Removed

- `ids.py` and its advisory-lock id allocation, and the URL lock that serialised
  check-then-insert. Both existed only to work around what the schema now enforces.
- The URL string fallback and opportunistic hash backfill, which existed to recognise
  un-normalised v1 rows.

### Fixed

- **A version bump left `apps/api/uv.lock` stale.** The lockfile records the API
  package's own version, `make version-set` never relocked it, and `make version-check`
  never looked, so the first `uv run` after a release commit rewrote it. `version-set`
  now relocks, and `version-check` fails on a stale lockfile for `apps/api` or `db`. It
  unsets `UV_FROZEN` to do so, because under it, as in CI, `uv lock --check` only checks
  that the file parses.

- **IPv6 URLs were stored invalid.** `http://[::1]:8080/x` normalised to
  `http://::1:8080/x` because the brackets were dropped when the host was reassembled.
- **`trkCampaign` never matched as a tracking parameter.** It was listed in mixed case
  and keys were lowercased before the lookup. It has since left the list (ADR 0011);
  entries are now lowercase and matching is case-insensitive.
- **`DB_NAME=... make <target>` acted on the `.env` database, not the one named.** The
  Makefile read `.env` with `:=`, which replaced a value from the environment, and make
  exports a variable that arrived from the environment, so the recipe saw the `.env` value
  too. `DB_NAME=page_history_test make migrate` announced nothing wrong and migrated the
  real database. They are `?=` now, and the environment wins. `schema-drop` had the same
  flaw a second time: it re-read `.env` in the shell, so `DB_NAME=scratch make schema-drop
  CONFIRM=yes` would have dropped the real database. It now reads `.env` for the password
  only, and says which database it is dropping.
- **`make schema-drop` failed part way on any database past revision `0001`.** It ran
  only `drop_tables.sql`, whose `bookmark` is referenced by `0002`'s tables. It now runs
  every revision's drop script, newest first.
- **Saving a link from the context menu gave it the wrong title.** The extension sent the
  link's URL with the current tab's title, so the saved page carried the title of the
  page that linked to it. A link save now sends no title and the crawler supplies one.
  The choice is a pure function, `contextMenuTarget`, so `node --test` covers it.

- **CI had failed on every push, and neither job reached its tests.** The `check` job
  passed `UV="uv --project apps/api --frozen"`, which put `--frozen` in front of `sync`,
  where uv does not accept it. `UV_FROZEN=1` now covers every uv command in the run,
  including the `uv run` calls inside make targets, which the flag never reached anyway.
  The `postgres` job sourced a `.env` that CI does not have. Behind that, it ran
  `postgres:16`, which has no pgvector, so revision `0002` could never have migrated
  there. It now runs `pgvector/pgvector:pg18`, matching the real server, and installs the
  extension from `db/schema/bootstrap.sql` before the suite. The actions are bumped to
  their node24 majors.
- **`make test-pg` failed locally from the moment `0002` landed.** `make db-bootstrap`
  only ever reached `DB_NAME`, never `<DB_NAME>_test`. It now takes `DB=`, and the
  migration's missing-extension message names the database, so the remedy it prints is
  `make db-bootstrap DB=page_history_test` rather than a command that fixes a different
  database. `test-pg` no longer requires `.env`, and when `DB_NAME` is unset it falls back
  to the same default as `config.py`, so the real-database refusal still has something
  to compare against.
- **Nothing checked that the schema runs without a superuser**, though ADR 0009 and the
  plan both rest on it. Every Postgres test connected as whoever `TEST_DATABASE_URL`
  named: `postgres` in CI, and a local `api` that was itself a superuser. A migration
  needing a privilege the real role lacks would have passed everywhere it was tested.
  `test_the_schema_needs_no_special_privileges` migrates, writes a vector and queries by
  distance, and downgrades, as a role with no SUPERUSER, CREATEDB or CREATEROLE. From a
  superuser connection it creates that role and switches to it with `-c role=`, so the
  tables are really created by and owned by it. From an ordinary connection it checks
  that the connecting role holds none of those attributes. It is first in its module on
  purpose: when it ran last, a superuser-only `CREATE EXTENSION` injected into a schema
  file slipped past it, because an earlier superuser test had already installed the
  extension. The alembic test config also escapes `%` now, which configparser would
  otherwise read as interpolation in a percent-encoded URL.

- **The extension could never reach the API.** `BookmarksApi` held `globalThis.fetch` in
  a field and called it as `this.fetch(...)`, so the receiver was the client object
  rather than the window; Chrome throws `Illegal invocation` for that, and every request
  failed before it was sent. The default now wraps the call instead of holding the
  function. Node's `fetch` does not check its receiver, which is why 41 passing tests
  could not see it — the new test's stand-in is as strict as the browser.
- The extension reports *why* a request failed. Every network failure arrived as
  `Cannot reach <url>`, which cannot tell a stopped API from Chrome's local-network-access
  restriction from a CORS refusal; it now carries the browser's own message.
- **No CORS handling at all.** Every client of this API is a browser, and a missing header
  there does not look like a server problem: the request arrives, the handler runs, the
  log records a 200, and the browser discards the response. Extension origins are matched
  by pattern, since an unpacked reload gets a new id; `CORS_ORIGINS` adds anything else.
  No `allow_credentials` — auth is a bearer token, and credentials plus a permissive
  origin rule is how a CORS policy becomes a vulnerability.
- The Postgres schema-diff test required `CREATEDB`. It built the models into a second
  *database*; it now builds them into a `models_mirror` schema of the same one, which
  needs only what the database owner already has. It also leaked an engine on the
  exception path, surfacing as a `ResourceWarning` promoted to a teardown error two tests
  later. The diff now compares enum labels as well: `str()` on a reflected type uses the
  generic dialect, where an enum renders as `VARCHAR(<longest label>)`, so it could not
  tell an enum from a varchar of the same width.

- **`make db-connect` printed the database password.** `DB_PASSWORD` was a make variable
  and the recipe was not silenced, so make echoed the line with the value already
  substituted — into the terminal, the scrollback, and any log. The password is no longer
  a make variable at all; the recipes read it in the shell, where make never sees it.
- `make test-pg` refuses a `TEST_DATABASE_URL` pointing at the configured database. That
  suite creates and drops tables, and checking only that the variable was *set* is not a
  guard — the dangerous value is the one aimed at real data. It also now prints the
  `createdb` line needed to make a scratch one.

- **A half-applied database could never be migrated again.** `CREATE TYPE tag_source`
  failed with "already exists" on every retry, because Postgres has no
  `CREATE TYPE IF NOT EXISTS` and a type is not removed by dropping tables. It is now
  created only when absent, accepted silently when its labels match, and **rejected
  loudly** when they differ — re-runnable without being blind. Tables are deliberately
  *not* idempotent: `CREATE TABLE IF NOT EXISTS` would accept a differently-shaped table
  and hide real drift.
- `make schema-drop CONFIRM=yes` resets a database to nothing, dropping `alembic_version`
  as well. `db/schema/drop/drop_tables.sql` cannot do that itself — it runs as the
  migration's downgrade body and alembic writes to that table immediately afterwards —
  so without the separate drop, a reset would leave alembic believing `0001` was applied
  and `make migrate` would be a silent no-op.
- `make db-doctor` now lists enum types. A database holding a type and no tables is
  precisely the state that produced this failure, and nothing reported it.

- **`alembic upgrade head` required the API package to be installed.** `env.py` imported
  `bookmarks_api.config` for the database URL, so running it from a `db/`-only environment
  died with `ModuleNotFoundError`. The schema belongs to the project rather than to one
  service, so the dependency is now gone: `db/migrations/dburl.py` resolves the URL from
  the same `.env` files using only the standard library, and `bookmarks_api` is imported
  solely for `--autogenerate`, and only if present. `db/` has its own `pyproject.toml`
  needing alembic, sqlalchemy and psycopg.

- **`make migrate` failed with "Path doesn't exist: migrations".** `script_location` in
  `db/alembic.ini` was relative, so alembic resolved it against the working directory
  rather than against the file — it worked only while alembic happened to be run from
  `db/`. Now `%(here)s/migrations`. The same cwd-relative trap that hid `.env` from the
  settings a few commits earlier.
- The Postgres suite built its own alembic `Config` and set `script_location` itself, so
  it never exercised the shipped value — which is how a broken setting survived a green
  test run. It now loads `db/alembic.ini` as shipped and overrides only the URL.

- **Migrations were being silently rolled back.** `alembic upgrade head` logged
  `Running upgrade -> 0001`, exited 0, printed no error, and left an empty database. The
  connection diagnostic added alongside the `page_history` rename executed on the
  migration's *own* connection before `context.configure()`. SQLAlchemy 2.0 opens a
  transaction on a connection's first `execute()`, and alembic's `begin_transaction()`
  returns a no-op when handed a connection already in one — so nothing committed and
  closing the connection discarded the whole migration. The diagnostic now runs on a
  connection of its own.
- The `tag_name_not_blank` check used `btrim`, which is Postgres-only and blocked running
  the migration against anything else. Now `trim`, which is standard SQL.
- `env.py` no longer overwrites an explicitly configured `sqlalchemy.url`, so alembic can
  be pointed at a scratch database.
- The alembic tree moved to `db/` at the repo root — the schema belongs to the project
  rather than to one service. `config.ALEMBIC_INI` and `config.MIGRATIONS_DIR` name its
  location once, so moving it again is a single edit rather than a hunt through tests,
  Makefile targets and error messages.
- Added `make migrate-revision M="..."`.

### Documentation

- Recorded the PostgreSQL version floor the target schema assumes (12+ for generated
  columns, pgvector 0.5+ for M3), and a preflight check before the first migration.

## [0.1.0] - 2026-09-20

First release. See [release_notes/v0.1.0.md](release_notes/v0.1.0.md) for details.

### Added

- Monorepo layout: `apps/api` (FastAPI), `apps/browser` (Electron, placeholder),
  `packages/shared-types`.
- API v2 at `/api/v2`, running against the existing v1 database schema with no migration:
  bookmarks with idempotent save, tag listing with usage counts, and health.
- Bearer-token authentication on every write. With no tokens configured, writes are
  refused with 503 rather than allowed.
- URL normalisation (`urlnorm.py`) with 24 tests — the foundation for deduplicating the
  2,216 duplicate rows in the existing corpus.
- Tag intersection queries: `?tags=python,fastapi&mode=all`, plus `?untagged=true` for
  working the untagged backlog.
- Alembic, with additive revision `0001`: real sequences to replace `SELECT MAX(id)+1`, and
  the index on `bookmark_tag(tag_fk)` that has never existed. The DDL stays in
  `migrations/sql/` so it remains reviewable as SQL and usable with `psql -f`.
- Schema guard: the API refuses to start when the database is not at the Alembic revision
  the code requires, naming both revisions and the command to fix it. A database *ahead* of
  the code fails too.
- `API_CONTRACT_VERSION`, reported by `/api/v2/health` alongside the release version and the
  database's current revision, so a client can check compatibility at startup.
- Advisory-lock id allocation as a fallback until that migration is applied.
- Test suite: 66 API tests and 9 for the version script, none requiring infrastructure,
  plus an opt-in Postgres suite (`-m postgres`) covering sequences, advisory-lock id
  allocation and the migration itself.
- `scripts/version.py` to keep the version consistent across `package.json`,
  `pyproject.toml` and `__init__.py`, with its own tests.
- Documentation set under `doc/`: a frozen audit, the architecture, a living plan, and
  ADRs 0001–0005 (0004 superseded by 0005).
- Release process adapted to this repo: `CHANGELOG.md`, `release_notes/`, a single
  enforced version across `package.json`, `pyproject.toml` and `__init__.py`, `make check`
  as the release gate, and a CI workflow running the same checks.

[Unreleased]: https://github.com/peterlharding/smart-browser/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/peterlharding/smart-browser/releases/tag/v0.3.0
[0.2.1]: https://github.com/peterlharding/smart-browser/releases/tag/v0.2.1
[0.2.0]: https://github.com/peterlharding/smart-browser/releases/tag/v0.2.0
[0.1.0]: https://github.com/peterlharding/smart-browser/releases/tag/v0.1.0
