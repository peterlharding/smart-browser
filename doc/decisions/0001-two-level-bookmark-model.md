# 0001 — Split the URL from the save

- **Date:** 2026-09-20
- **Status:** Accepted
- **Supersedes:** the single-user assumption in the original `architecture.md`

## Context

The system was single-user by accident rather than design: `application_user` and
`login_session` exist, but no bookmark is owned by anyone. Going multi-user resolves two ways.

The obvious one is an `owner_id` column on `bookmark`, `tag` and the link table. It is an
`ALTER TABLE` rather than a restructure.

The cost of that shows up in M2 and M3, which are the project's entire cost centre: fetching
and embedding 7,256 distinct URLs, then an LLM pass over 7,655 untagged bookmarks. With
`owner_id` on `bookmark`, two users saving the same page produce two rows, so the same page is
crawled twice, extracted twice and embedded twice. The expense scales with users × URLs when
the underlying work is per-URL.

## Decision

Two levels:

- **`bookmark`** is the URL itself — global, unique on `url_hash`, owned by nobody. It carries
  the canonical title, the crawl result, and exactly one `bookmark_content` row with one
  embedding.
- **`user_bookmark`** is the personal save — `(user_id, bookmark_id)` unique, carrying
  `saved_at`, `title_override`, `notes`, visit counts and `deleted_at`.
- **`bookmark_tag`** hangs off `user_bookmark`, not `bookmark`.

## Consequences

**Good.** Crawl and embedding cost is per-URL and flat as users are added. Global dedupe on
`url_hash` is genuinely global. "Who else saved this" becomes answerable. Tag centroids can
pool across users, which matters most for a new user who has no examples of their own.

**Bad.** One more table and an extra join on every read path. The M1 migration splits 9,472
rows into two levels instead of adding a column — more work, and the merge logic for the 2,216
duplicates has to run before the split rather than after.

**Watch.** `bookmark` rows are shared, so every read must join through `user_bookmark` filtered
by `user_id`. A query that reaches `bookmark` directly leaks the existence of other users'
saves. This is the one invariant worth a test of its own.

**Note.** Pooled tag centroids mean one user's tagging influences another's suggestions. That
is desirable here and would not be in a tenancy-isolated product; revisit if that changes.
