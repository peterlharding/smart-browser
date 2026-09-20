# Smart-Browser documentation

| Document | What it is | Lifetime |
| --- | --- | --- |
| [`audit-2026-09-20.md`](audit-2026-09-20.md) | Measured state of the `bookmarks-pg` corpus at project start | **Frozen.** A dated snapshot — never edit it; take a new one if you re-measure |
| [`architecture.md`](architecture.md) | Target design: shell, schema, API, categorization pipeline | Stable. Changes when a decision changes |
| [`plan.md`](plan.md) | Migration steps, milestones, open questions | Churns. Expect to edit this weekly |
| [`decisions/`](decisions/) | One file per settled decision (ADR), numbered and dated | Append-only |
| [`NOTES.md`](NOTES.md) | Orientation: where things live, the numbers that drive the design, settled decisions at a glance | Living |

Process documentation lives at the repo root, not here: [`../RELEASING.md`](../RELEASING.md)
for the release checklist and commit conventions, [`../CHANGELOG.md`](../CHANGELOG.md) for
the record of changes.

## Why the split

These started as one document doing three jobs with three different lifetimes. The audit is
evidence and must not be rewritten — its numbers are the justification for the design, and a
design doc that silently updates its own evidence can't be audited later. The architecture is
stable. The plan changes constantly. Keeping them in one file means either the plan goes stale
or the evidence gets overwritten.

## Conventions

- `doc/`, not `docs/` — matches the existing `bookmarks-pg` repo.
- Decisions get a number when they're settled, not when they're proposed. Open questions live
  in `plan.md` until then.
- Anything with a date in the filename is a snapshot and is never edited after the fact.
