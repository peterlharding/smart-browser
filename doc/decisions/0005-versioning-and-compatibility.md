# 0005 — Versions label releases; checks enforce compatibility

- **Date:** 2026-09-20
- **Status:** Accepted
- **Supersedes:** [0004](0004-single-version-monorepo.md)

## Context

ADR 0004 put one semver across the whole monorepo, including the database schema. Two
problems with that, raised in review.

**The schema was never a semver thing.** Schema state is *ordinal*: revision `0007` has
either been applied or it has not. There is no coherent reading of "schema 2.3.1", and no
migration is ever "backward-compatible" in the sense PATCH means — every migration is
breaking for code that predates it. Putting it in the version scheme was a category error.

**The single version asserts something false.** ADR 0004 argued browser and API "ship
together". They do not. The browser is a desktop application installed on the user's
schedule; the API is deployed on yours. A user on 0.4.0 *will* meet an API at 0.7.0. That
is what desktop software is, not a process failure to be disciplined away.

But independent semver does not fix it either. Browser 0.4.2, API 0.7.1, schema at 0009 —
three honest numbers, and still nothing that says whether they work together. That makes the
coordination problem visible without answering it, which is the familiar trap.

The realisation: **version numbers cannot enforce compatibility, and were never going to.**
What enforces compatibility is a check.

## Decision

Three separate concerns, handled three ways.

**1. Schema — Alembic revisions, not versions.** `db/migrations/` is an Alembic tree.
The DDL stays in `migrations/sql/*.sql` so it is reviewable as SQL and `psql -f` still works
in an emergency; the revision reads that file, which keeps one copy of the statements.

**2. API contract — `API_CONTRACT_VERSION`, independent of the release.** The `v2` in
`/api/v2`, surfaced by `/api/v2/health`. It moves only on a breaking change, which should be
rare. The browser asserts it at startup, so a mismatch is a clear message rather than a 404
on one route.

**3. Release version — one for the repo, for now.** A label for changelogs and support
("I'm on 0.4.2"), not a safety mechanism. `scripts/version.py` keeps it consistent across
`package.json`, `pyproject.toml` and `__init__.py`.

And the two checks that do the actual work:

- **API → database.** `schema_guard.verify()` runs at startup and refuses to boot when the
  database is not at `REQUIRED_SCHEMA_REVISION`. A test asserts that constant equals the
  Alembic head, so the two cannot drift.
- **Browser → API.** The client asserts `contract` from `/health` at startup (wired at M5).

## Consequences

**Good.** The failure that actually hurts — code expecting a column that is not there —
becomes a process that will not start and says why, instead of a 500 on one endpoint at an
inconvenient hour. A database *ahead* of the code fails too, which is the case people
usually forget. Splitting release versions later becomes a non-event, because nothing
depends on them being equal.

**Bad.** Alembic is real machinery for a project with one migration. Justified by M2, which
is a multi-step transformation of 9,472 rows and wants proper revisions, but it is early.

**The trigger to split release versions**, written down so it is recognised rather than
argued about: *the first time a browser build runs against an API deployment it did not ship
with.* At that point `apps/browser` and `apps/api` get their own versions,
`scripts/version.py` drops to `apps/api` plus the root, and the contract check becomes the
only thing keeping them honest — which it already was.

## What carries over from 0004

Still true, and unchanged:

- `packages/shared-types/openapi.json` is committed though generated; CI fails when stale.
- `pytest` runs with `filterwarnings = ["error", ...]`, so the "no warnings" requirement in
  the release checklist is enforced rather than remembered.
