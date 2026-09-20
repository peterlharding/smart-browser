# 0007 — This is a new implementation

- **Date:** 2026-09-20
- **Status:** Accepted
- **Extends:** [0006](0006-clean-schema.md)

## Context

ADR 0006 stopped the API accommodating the v1 `bookmarks-pg` tables, but left the
predecessor in the plan as a *source*: M2 was an importer, M7 retired the old `/xyzzy`
endpoint, and the guiding constraint still promised the old extensions would keep working.

That direction is now reversed. The predecessor will be brought into line with this
project rather than this project inheriting from it.

## Decision

Smart-Browser is a new implementation with no compatibility obligation to what came before.

- **No importer milestone.** Bringing the existing bookmarks across is work on the other
  project, against whatever shape it ends up in, and is out of scope here.
- **No `/xyzzy` retirement milestone.** That endpoint belongs to the other project.
- **The old Chrome and Firefox extensions are not clients.** `apps/extension` is the
  extension. The guiding constraint that the browser is "a second client of the same API"
  still holds — the other client is that extension, not an inherited one.
- **Nothing in this codebase explains itself by reference to the old schema.** A comment
  saying a column exists "because the v1 table had X" is describing a constraint that no
  longer applies to anyone reading it.

## What the audit is now

`doc/audit-2026-09-20.md` stays, unedited, and stays load-bearing — but as **evidence about
the problem**, not as a description of data being migrated.

Its numbers are why this system is shaped as it is, and they would be just as compelling
measured from someone else's bookmark collection:

- **80.8% of bookmarks untagged** — tagging that happens later doesn't happen. This is why
  the save sheet exists, and why AI categorization is not a feature to add at the end.
- **1.44 tags on the average tagged bookmark** — a schema supporting many tags does not
  produce many tags. The interaction has to.
- **23% duplicate rows** — an endpoint that inserts unconditionally will accumulate
  duplicates indefinitely. This is why `UNIQUE (url_hash)` exists.
- **32 near-duplicate tags in a 567-tag vocabulary, and one blank tag on 43 bookmarks** —
  free-text tag entry decays without normalisation and aliasing.

Eleven years of a system's actual failure modes is unusually good design evidence. Throwing
it out because the rows are not being migrated would be discarding the most valuable thing
the predecessor produced.

## Consequences

**Good.** Nothing in the code or the plan is shaped by a schema nobody will run again. The
milestone list describes building a product rather than escaping a previous one.

**Bad.** The 9,472 bookmarks are not here and no milestone brings them. That is a
deliberate deferral to the other project, not an oversight — but until it happens, this
system has no data, and the AI categorization work at M4 will need some.

**Numbering.** Surviving milestones keep their numbers rather than being compacted, so that
references to M3 and M4 in earlier ADRs stay correct. The gaps at M2 and M7 are where the
importer and the `/xyzzy` retirement were.

## Note on `/api/v2`

The `v2` in the URL is a fossil: it was v2 because the predecessor was v1. It is now the
first contract version of a new system, and its name is wrong. Renaming costs a breaking
change for one client, which is as cheap as it will ever be — but it is a contract change
and is left as an open question in `plan.md` rather than taken silently.
