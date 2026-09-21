# 0014 - What a tag name may be, and aliases on every path

- **Date:** 2026-09-21
- **Status:** Accepted
- **Builds on:** [ADR 0002](0002-global-tag-vocabulary.md) (the vocabulary and its aliases), [ADR 0006](0006-clean-schema.md) (no length cap)

## Context

The review of 2026-09-21 found four tag bugs, and reproducing them against a running API found two more.

1. **Nothing checked what a tag name contains.**
   `red,green` was saved, and `?tags=red,green` splits on the comma, so no filter could ever reach it.
   `machine learning` and names with tabs were saved too, although every client that types tags splits on whitespace.
2. **Aliases resolved on the way in and nowhere else.**
   Saving `boorstrap` stored `bootstrap`, but `?tags=boorstrap` found nothing and `DELETE .../tags/boorstrap` was a 404.
3. **`PATCH` with an alias rewrote provenance.**
   Its diff compared the alias with the stored name, deleted the link, and re-added it as `source = user`, so an AI suggestion became the person's own choice.
4. **A tag containing `/` could be saved and never removed.**
   The path is decoded before routing, and a plain `{tag_name}` parameter stops at the first slash.
5. **The extension refused tags over 32 characters.**
   That was the retired schema's `varchar(32)`, which ADR 0006 removed; the server has had no limit since.

## Decision

**A tag name is trimmed and lowercased, and contains no comma, whitespace or control character.**
A comma is the separator in `?tags=`.
Whitespace is the separator every client that types tags uses, so a name with a space in it can be stored but never typed.
Anything else is a tag: `c++`, `c#`, `ci/cd`, `日本語`, and emoji, including ones joined with zero-width joiners, which are format characters rather than control characters.
There is still no length limit, as ADR 0006 decided.

Every write path applies the rule, as a 422 whose message names the tag and the rule.
A blank entry in a list of tags to save or set is dropped, since a trailing comma in a typed list is not an error; in an explicit "add these tags" request it is refused, as before.

**Every path that names a tag resolves aliases**, not only the one that writes: filtering, removing and `PATCH`, as well as saving.
In a `mode=all` filter an alias and its tag are one tag.
`PATCH` compares canonical names, so a tag named by its alias keeps its existing link and that link's `source`.

**`DELETE /bookmarks/{id}/tags/{tag_name}` matches the rest of the path**, so `ci%2Fcd` removes `ci/cd`.
The URL clients call is unchanged.

**The extension has no length limit either**, and shows the server's own message when a save is refused, rather than a generic one.

## Options not taken

- **Allowing whitespace, and changing the clients to split only on commas.**
  `machine learning` reads better than `machine-learning`.
  But the save sheet's parsing and autocomplete are built on whitespace separation, every tag the audit quotes is a single token, and a vocabulary holding both spellings is the drift the audit measured.
  An alias can still map `machinelearning` or `ml` to the canonical tag.
- **Forbidding `/`.**
  Simpler for the route, and wrong for names like `ci/cd` and `tcp/ip`.
- **Rewriting invalid names** (replacing a space with a hyphen) instead of refusing them.
  Silent rewriting is how a vocabulary ends up holding spellings nobody chose.
  A 422 that names the tag and the rule lets the client, or the person, decide.

## Consequences

- No migration.
  The real database's three tags already obey the rule, checked before this change.
  A database that holds names breaking it keeps them; they cannot be created again.
- M4 has to emit valid names.
  Its prompt should ask for single tokens, and its output goes through the same validation and alias resolution as a person's.
