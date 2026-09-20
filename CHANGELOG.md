# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Add entries under `## [Unreleased]` as part of each change, not at release time.

## [Unreleased]

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

[Unreleased]: https://github.com/peterlharding/smart-browser/commits/main
