# 0004 — One version for the monorepo, enforced by a check

- **Date:** 2026-09-20
- **Status:** Superseded by [0005](0005-versioning-and-compatibility.md)

> Kept for the record. 0005 corrects two things: the database schema does not belong
> in a semver scheme at all, and the claim below that the browser and API "ship
> together" is false for installed desktop software. The single release version
> survives, but as a label rather than a guarantee.

## Context

`RELEASING.md` was adopted from another project, where "the version" meant one field in one
`package.json`. This repo is polyglot: the version appears in `package.json`,
`apps/api/pyproject.toml`, `apps/api/src/bookmarks_api/__init__.py` — which is what
`/api/v2/health` reports — and will appear in `apps/browser/package.json` at M5.

Four hand-maintained copies of the same string drift within a week. The failure is quiet:
a release tagged `v0.3.0` ships an API reporting `0.1.0`, and nobody notices until a bug
report cites the wrong version.

The alternative is independent versions per package. That is the right answer when packages
are consumed separately.

## Decision

**One version for the whole repo**, canonical in `package.json` because that is what
`npm version` writes.

`scripts/version.py` writes every location together. `make version-check` fails on drift and
runs as the first step of `make check`, which the release checklist requires. The script has
its own tests — it is the only thing standing between a release and a wrong version number,
so an untested one would be false assurance.

## Consequences

**Good.** The version in `/api/v2/health` is always the released version. A patch to the
browser bumps the API too, which is honest: they ship as one artifact and a browser against a
mismatched API is broken anyway. Drift is a build failure, not a discovery.

**Bad.** Version numbers advance for components that did not change, so "what changed in
0.4.0" must be read from the changelog rather than inferred from which package moved.

**Revisit if** the API is ever consumed by something other than this browser — a third-party
client, or a public API. Splitting versions after the fact is disruptive, so the trigger is
worth watching for rather than discovering late.

## Also decided here

- `packages/shared-types/openapi.json` is **committed**, though generated. It is the contract
  the browser client is built from, so a diff against it in review is the signal that an API
  change is breaking. CI regenerates it and fails if the committed copy is stale.
- `pytest` runs with `filterwarnings = ["error", ...]`. The release checklist demands a run
  with no warnings; making that the default means a new deprecation fails the suite instead
  of scrolling past. The third-party warnings we cannot fix are listed explicitly rather than
  blanket-ignored.
