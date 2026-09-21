# 0009 — The crawl queue is a table, drained by a worker

- **Date:** 2026-09-21
- **Status:** Accepted
- **Options compared:** [`m3-crawler-options.md`](../m3-crawler-options.md)

## Context

M3 fetches each saved page for its title, text and embedding. The question was where the
fetch runs: inside `POST /bookmarks`, or in a separate process fed by a queue.

Fetching inside the request is less machinery — no second process, no new table — and for
one person saving a few pages a day it would work. Three things decided against it.

1. **The save sheet is the product.** Its latency would become the latency of whatever
   server the page lives on. An uncontrolled multi-second call is the one thing that
   interaction cannot afford.
2. **Retry needs somewhere to live.** A failed fetch leaves `fetched_at` NULL and nothing
   ever looks again; the retry policy becomes "save it again by hand".
3. **M4 needs a queue regardless.** Categorising 7,000 already-saved bookmarks is not a
   save request. Fetching in-process defers that machinery rather than avoiding it, and
   pays for it twice.

`BackgroundTasks` was considered and rejected: it fixes latency only. The work still lives
in the API process, still has no retry, still dies on restart — and now fails invisibly,
because nothing records that it was ever owed.

## Decision

`crawl_job` is a table in the same database, and a separate worker drains it.

- **`bookmark_id` is the primary key.** One outstanding crawl per URL is an invariant, so
  the database enforces it rather than the enqueue code remembering to check.
- **The job is written in the transaction that saves the bookmark.** Both commit or
  neither does; "saved but never queued" is unreachable rather than merely unlikely.
  `test_the_job_is_written_in_the_callers_transaction` fails if enqueueing ever grows a
  commit of its own.
- **Claiming is `FOR UPDATE SKIP LOCKED`.** A second worker is then safe to start, and
  "it is going slowly" has an answer that is not a code change.
- **Backoff is a timestamp, not a sleep.** It survives a restart, and a second worker
  honours it.
- **Nothing is queued for a page already fetched**, and a re-save never disturbs a job in
  flight — the extension posts on every save sheet, and resetting a running job would
  hand the same page to a second worker.

**Not a generic job table.** M4's categorisation gets its own, copying this pattern. A
`job(kind, payload jsonb)` serving both is the shape that becomes a framework nobody
asked for, and the two differ in payload, retry policy and cost per item.

**Postgres, not Redis or a broker.** The transactional guarantee above is the entire
design, and it exists only because the queue and the data are in one database. A broker
would reintroduce the failure it was chosen to prevent.

## Consequences

- A second process to run. At one user that is `make worker` when you want the backlog
  cleared; the queue is durable, so a worker that is not running means the fetch waits,
  not that saving fails.
- Politeness, timeouts, size caps, content-type filtering and `robots.txt` have a place to
  live. None of them could live honestly inside a save request.
- The worker is testable without the network: it is a loop around an injected fetcher, and
  claiming, backoff and the failure path are ordinary database tests.
- Revision `0002` adds `bookmark_content`, `job_state` and `crawl_job`. It does **not**
  create the `vector` extension: pgvector is not trusted, so that needs a superuser
  (`make db-bootstrap`), and the migration asserts rather than installs.
