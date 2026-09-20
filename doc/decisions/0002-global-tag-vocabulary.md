# 0002 — One tag vocabulary, ownership on the link

- **Date:** 2026-09-20
- **Status:** Accepted

## Context

With multiple users, tags can be global (one shared vocabulary), per-user (`tag.owner_id`,
unique on `(owner_id, name)`), or hybrid (shared canon plus private namespaces).

The existing corpus is 567 tags curated over eleven years, with 2,623 links concentrated in a
long tail — the top tag has 124 uses and most have a handful. That distribution is already thin
for the embedding work in M3.

## Decision

The `tag` table is global and has no owner. Ownership lives on `bookmark_tag`, which hangs off
`user_bookmark` (see ADR 0001). `tag_alias` is likewise global.

## Consequences

**Good.** The existing 567 tags become the shared starting vocabulary rather than one user's
private set. Centroids pool across all usage, so tag suggestions work for a user with no
history. A tag merge fixes the vocabulary for everyone at once, which is the whole point of
`tag_alias` — per-user vocabularies would mean the 32 near-duplicates found in the audit could
re-accumulate independently in every namespace.

**Bad.** No private taxonomies. A user cannot have a tag nobody else sees, and cannot disagree
with a merge. Tag *names* are visible to everyone; only the links are private.

**Rejected:** per-user tags, because a new user would start from an empty vocabulary and
fragmented centroids — worst exactly when they have the fewest examples to work from.

**Reversible?** Partially. Adding a private namespace later is additive (`tag.owner_id`
nullable, NULL meaning global). Going fully per-user later is not.
