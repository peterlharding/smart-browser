# 0006 — Build on a clean schema, not the v1 tables

- **Date:** 2026-09-20
- **Status:** Accepted
- **Supersedes in part:** the "API v2 over the existing schema" approach released in 0.1.0

## Context

M0 deliberately ran against the existing `bookmarks-pg` tables so that nothing had to
change before the API could exist. That constraint shaped a lot of code:

- `SELECT MAX(id)+1` id allocation, and an advisory-lock module (`ids.py`) to make it safe
- an advisory lock on `url_hash` to serialise check-then-insert, because a `UNIQUE`
  constraint was impossible while 2,216 duplicate URLs remained
- URL matching that tried the hash, then fell back to raw and normalised strings, and
  back-filled the hash opportunistically for rows the v1 app had inserted
- a `varchar(32)` cap on tag names, rejected with 422 rather than truncated
- `host` holding the posting client, `used` standing in for `created_at`, and response
  schemas using target field names over v1 storage to keep the contract stable across M2

All of it existed to accommodate a schema that is being retired. The owner is cleaning up
`bookmarks-pg` separately, so the accommodation has no beneficiary.

## Decision

The API owns a **new database** built from the target schema in `architecture.md` §2:
`app_user`, `user_identity`, the `bookmark` / `user_bookmark` split, a global `tag`
vocabulary with `tag_alias`, and `bookmark_tag` carrying `source` and `confidence`.

Revisions `0001` and `0002` are deleted and replaced by a single revision creating that
schema. They remain in history under the `v0.1.0` tag; nothing ever applied them to a live
database, and the new database has never seen them.

Two simplifications taken at the same time:

- **No `citext`.** Tag names are lowercased by the application on every path, so a plain
  `UNIQUE (name)` is sufficient and the schema needs no extension.
- **`bookmark_content` and `tag_centroid` are deferred to M3**, where they belong, since
  they are the only tables needing `pgvector`.

## Consequences

**Good, and the point of the change:** `UNIQUE (url_hash)` is now possible, so "save the
same page as often as you like and never get a duplicate" is enforced by Postgres rather
than by application code being correct. `INSERT ... ON CONFLICT DO NOTHING` replaces
check-then-insert entirely: no lock, no race, no window. That was the strongest available
argument for this change, and it only became available once legacy rows stopped mattering.

`ids.py` and `lock_url` are deleted outright. Both existed solely to work around what the
constraint now handles.

**Bad.** The existing 9,472 bookmarks are not in the new database. Importing them becomes a
separate exercise against whatever the cleaned-up `bookmarks-pg` looks like, and the dedupe
and tag-alias work planned for M2 moves into that importer.

**Unchanged.** `doc/audit-2026-09-20.md` remains valid and remains the justification for the
design. Its numbers describe the corpus this system is being built for, whether or not those
rows are migrated: 80.8% untagged is still why AI categorization comes before the browser,
and 1.44 tags per tagged bookmark is still why tagging must happen at save time.

The API contract does not change. `schemas.py` already used the target field names, which is
why the extension needs no modification for any of this.
