# 0008 — The API path is `/api/v1`

- **Date:** 2026-09-21
- **Status:** Accepted
- **Amends:** [0005](0005-versioning-and-compatibility.md)

## Context

The API was mounted at `/api/v2` from the first commit, and the `2` never meant anything
here: it was inherited from `bookmarks-pg`, where v1 was the original contract and v2 the
one the predecessor grew into. ADR 0007 severed that lineage — this is a new
implementation with no compatibility obligation to what came before — which left a version
number whose only justification was a project this one no longer descends from.

A wrong-but-stable name is a small cost, paid every time someone reads the path and looks
for the v1 that never existed. What makes it worth fixing *now* is that the cost of fixing
it only grows: today there is exactly one client, one constant and one generated contract
file. After M5 there is a browser in the field, and after any real deployment there are
saved URLs.

## Decision

The contract is `/api/v1`, and `API_CONTRACT_VERSION` is `1`.

This is the first contract version of this system. The next breaking change makes it `2`,
and that `2` will mean what ADR 0005 says it means.

**History is not rewritten.** `CHANGELOG` entries under `0.1.0`, `release_notes/v0.1.0.md`
and earlier ADRs still say `/api/v2`, because that is what the release they describe
actually served. Only documents describing the *current* system were changed.

## Consequences

- One client changed: `apps/extension/src/lib/api.js` and the options page's help text.
- `packages/shared-types/openapi.json` regenerated.
- Anything already pointing at `/api/v2` gets a 404 rather than a redirect. With one
  extension, one developer and no deployment, that is the whole blast radius — and a 404
  is a better signal than a silent redirect that lets a stale client keep working.
- The `contract` field in `/api/v1/health` now reports `1`. Nothing asserts it yet; the
  options page displays it, and the browser will assert it from M5.
