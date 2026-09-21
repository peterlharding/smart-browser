# Smart-Browser — where the work lives

**The repo is the source of truth.** This file is a pointer, kept short deliberately: an
earlier copy of the design lived here in full and immediately started drifting from the
version in the repo.

Repo: `git@github.com:peterlharding/smart-browser.git`
Checkout: `/Volumes/u/src/wip/browser/smart-browser` (note: `/u` is a symlink; folder
access must use the `/Volumes/u/...` path)

Predecessor: `/Volumes/u/src/wip/bookmarks/bookmarks-pg`
(`git@github.com:peterlharding/bookmarks-pg.git`). **Not a dependency and not a source.**
This is a new implementation; that project will be brought into line with this one later
(ADR 0007). Its value here is the audit.

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

Measured from eleven years of a real bookmarking system (`doc/audit-2026-09-20.md`). These
are facts about what happens when tagging is deferred, not facts about data being migrated:

- 9,472 bookmarks, **80.8% with no tags at all**
- 1.44 tags on the average tagged bookmark (1,148 of 1,817 have exactly one)
- 2,216 duplicate URL rows (23%)
- 9,081 with no title (96%)
- 567 tags, 32 near-duplicate pairs, one blank tag used 43 times

The consequences, which are the whole design: tagging must happen at the moment of saving
(the save sheet), duplication must be impossible by construction (`UNIQUE (url_hash)`), the
tag vocabulary needs aliasing to survive free-text entry, and AI categorization is what
makes a large collection navigable rather than a feature to add at the end.

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

**M0 done.** API v2 on a clean schema, bearer auth on every request, saves that cannot
duplicate, and a Chrome extension with a tag-on-save sheet. 145 tests across the API, the
extension and the release tooling. CI, release process, seven ADRs.

**The database is no longer empty** — the first end-to-end save landed on 2026-09-21
(extension → API → Postgres, read back through the docs page). Nothing bulk-imports the
old bookmarks; that is work for the other project (ADR 0007).

Next: M3 — the crawler. M1 (OAuth) is deferred behind it: it replaces a bearer token that
works, for one user, and it needs a deployment that can receive a callback. See
`doc/plan.md`.

Settled since: the API path is `/api/v1` (ADR 0008), and this runs locally for now.
Open questions in `doc/plan.md`: which LLM for categorization, and whether tags should be
hierarchical.
