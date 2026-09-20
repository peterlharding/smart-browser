# Smart-Browser — where the work lives

**The repo is the source of truth.** This file is a pointer, kept short deliberately: an
earlier copy of the design lived here in full and immediately started drifting from the
version in the repo.

Repo: `git@github.com:peterlharding/smart-browser.git`
Checkout: `/Volumes/u/src/wip/browser/smart-browser` (note: `/u` is a symlink; folder
access must use the `/Volumes/u/...` path)

Reference backend being modelled on: `/Volumes/u/src/wip/bookmarks/bookmarks-pg`
(`git@github.com:peterlharding/bookmarks-pg.git`)

## Documentation map

| File | What it is |
| --- | --- |
| `doc/audit-2026-09-20.md` | Frozen measurements of the existing corpus. Never edit — take a new dated snapshot instead. |
| `doc/architecture.md` | Target design: Electron shell, multi-user schema, OAuth, categorization pipeline, API v2 |
| `doc/plan.md` | Living: milestones M0–M7, open questions, decisions log |
| `doc/decisions/` | ADRs 0001–0005 (0004 superseded by 0005) |
| `RELEASING.md` | Release checklist and commit conventions |
| `CHANGELOG.md` | Keep a Changelog; add under `[Unreleased]` as you go |

## The numbers that drive every decision

From the 2025 dump of the existing database:

- 9,472 bookmarks, **80.8% with no tags at all**
- 1.44 tags on the average tagged bookmark (1,148 of 1,817 have exactly one)
- 2,216 duplicate URL rows (23%)
- 9,081 with no title (96%)
- 567 tags, 32 near-duplicate pairs, one blank tag used 43 times

The consequence: AI categorization is not a late feature, it is what makes the corpus
usable at all, and it must run as a backfill before the browser UI is worth building.

## Settled decisions

- Electron shell; extensions stay first-class clients of the same API
- Monorepo: `apps/api` (FastAPI), `apps/browser` (Electron), `packages/shared-types`
- Multi-user, with `bookmark` (the global URL) split from `user_bookmark` (the personal
  save) so crawling and embedding cost stays per-URL — ADR 0001
- One global tag vocabulary; ownership on the link — ADR 0002
- OAuth through the backend as confidential client; Google and GitHub — ADR 0003
- Versioning — ADR 0005, superseding 0004: three concerns, three mechanisms. Schema on
  Alembic revisions (ordinal, never semver); API contract version (`API_CONTRACT_VERSION`,
  the `v2`) separate from the release version; one release version for the repo as a
  *label*. Compatibility is enforced by two checks, not by numbers matching — the API
  refuses to start against a database at the wrong revision, and the browser asserts the
  contract version from `/health`. Split the release version the first time a browser build
  runs against an API deployment it did not ship with.
- Hybrid categorization: LLM for the backfill, local `bge-small` embeddings steady-state

## Status

M0 complete: API v2 over the existing schema, auth on writes, idempotent save, URL
normalisation, Alembic with the additive safety revision `0001`, schema guard, 75 tests,
CI, release process.

**Revision `0001` has not been applied to the live database, and that database has never
been stamped by Alembic** — so the API will refuse to start against it until either
`make migrate` or `make migrate-stamp REV=0001` has run. That refusal is deliberate.

Next: M1, identity — `app_user`, `user_identity`, the OAuth flow, token rotation.

Open questions are in `doc/plan.md`: which LLM for the backfill, tag hierarchy, and
confirming `bookmarks.performiq.com` as the deployment target.
