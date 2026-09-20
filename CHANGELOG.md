# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Add entries under `## [Unreleased]` as part of each change, not at release time.

## [Unreleased]

### Fixed

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

### Changed

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

### Added

- **Chrome extension** (`apps/extension/`): MV3, with a save sheet that shows existing tags
  and offers autocomplete ranked by your own usage. `⌘⇧B` to tag and save, `⌘⇧S` to quick
  save. Opening the popup is a lookup, never a write.
- `GET /api/v2/bookmarks/lookup` — read-before-write by URL.
- Soft delete on saves, with re-saving a deleted page restoring it rather than duplicating.
- `test_duplication.py` and `test_scoping.py` covering the two guarantees the schema buys.
- `scripts/version.py` now manages the extension's `package.json` and `manifest.json`,
  stripping the prerelease suffix for the manifest since Chrome rejects it.

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

[Unreleased]: https://github.com/peterlharding/smart-browser/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/peterlharding/smart-browser/releases/tag/v0.1.0
