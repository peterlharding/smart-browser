# M3 — where the crawler runs

> Sketch, not a decision. Two designs against the schema in
> [`architecture.md`](architecture.md), so the choice can be made on what each costs
> rather than on which sounds tidier. Settled once chosen: an ADR, then revision `0002`.

## What both need

The fetch itself is the same work either way, and so is the table it fills. Neither of
these is in dispute; they are the shared base the two options sit on.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE bookmark_content (
    bookmark_id bigint PRIMARY KEY REFERENCES bookmark(id) ON DELETE CASCADE,
    text        text,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(text,''))) STORED,
    embedding   vector(384),
    model       text,                       -- what wrote this row; a re-embed is detectable
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX bookmark_content_tsv_idx ON bookmark_content USING gin (tsv);
CREATE INDEX bookmark_content_emb_idx ON bookmark_content
    USING hnsw (embedding vector_cosine_ops);
```

Keyed by `bookmark_id`, not `user_bookmark_id`: content belongs to the URL, so ten people
saving the same page pay for one crawl and one embedding. That is ADR 0001 earning its
keep, and it is why `bookmark` already carries `title`, `description`, `site`,
`fetched_at` and `http_status` — the crawler fills columns that exist.

**`fetched_at IS NULL` means never fetched.** It does not mean dead, and it does not mean
failed. Whatever else is decided, that distinction has to survive.

### Prerequisite to check first

`CREATE EXTENSION vector` fails on a stock `postgres:18` image. Before any of this is
worth designing further, confirm the container has pgvector — `pgvector/pgvector:pg18`, or
the extension installed into the current image. One command:

```sh
make db-connect   # then: SELECT * FROM pg_available_extensions WHERE name = 'vector';
```

If it is missing, that is a container swap on a database with one save in it — trivial
now, not later.

---

## Option A — fetch on save, in the API process

`POST /bookmarks` upserts the bookmark as it does today, then fetches the page before
returning.

**Schema:** nothing beyond `bookmark_content`. The state is already expressible:
`fetched_at IS NULL` is the work queue, informally.

```text
extension ──POST──> API ──upsert──> bookmark
                     │
                     ├──GET the page (network, 0.2s … 30s … never)
                     ├──extract title/description/text
                     ├──embed (model in-process)
                     └──INSERT bookmark_content ──> 201/200 to the extension
```

**What it buys.** No second process, no new table, nothing to supervise. `make dev` is
still one command. For a single user saving a handful of pages a day, it would work.

**What it costs.**

- **Save latency becomes someone else's problem.** The extension's popup waits on the
  slowest thing in the request, and that is now a third-party server. The save sheet
  closing is the interaction; putting an uncontrolled multi-second network call inside it
  is the one place this project cannot afford to be slow.
- **A hung fetch holds a worker.** With the small worker count a local deployment runs,
  a few slow hosts is the whole API.
- **Retry has nowhere to live.** A 503 from the far end leaves `fetched_at` NULL, and
  nothing ever looks at it again. The retry policy becomes "save it again by hand".
- **The embedding model is ~130MB of process.** In-process means every API worker loads
  it, and API startup waits for it — on a code reload too.
- **M4 needs a backfill path anyway.** Categorising what is already saved is not a save
  request. Option A therefore does not remove the need for the machinery in Option B; it
  defers it, and pays for it twice.
- **It is hard to test honestly.** A fetch inside a request handler is tested either by
  hitting the network or by patching around it. The lesson from the extension's
  `Illegal invocation` applies: what the suite cannot reach, the suite cannot vouch for.

**The `BackgroundTasks` variant** — return 201 immediately, fetch after the response —
fixes latency and nothing else. The work still lives in the API process, still has no
retry, still disappears on restart, and now fails invisibly: nothing records that it was
ever supposed to happen.

---

## Option B — a queue in Postgres, drained by a worker

The API's job ends at "recorded that this needs fetching". A separate process does the
fetching.

```text
extension ──POST──> API ──┬── upsert bookmark          ┐ one transaction:
                          └── enqueue crawl_job        ┘ both, or neither
                                    │
                                201/200 (immediately)
                                    │
                       worker ──claim──> fetch ──> bookmark_content
                                    └── on failure: attempts+1, next_attempt_at
```

### B1 — no queue table

The queue is `SELECT * FROM bookmark WHERE fetched_at IS NULL`, claimed with
`FOR UPDATE SKIP LOCKED`.

Cheapest possible: no new table, no enqueue step, and a crash cannot lose a job because
the job *is* the bookmark row. But there is nowhere to put an attempt count, a next
attempt time, or an error, so a URL that 500s is retried forever at full speed, and
"never fetched" and "failed eleven times" are the same state. That gap is the whole
argument for B2.

### B2 — an explicit `crawl_job` table

```sql
CREATE TYPE job_state AS ENUM ('ready', 'running', 'done', 'failed');

CREATE TABLE crawl_job (
    bookmark_id     bigint PRIMARY KEY REFERENCES bookmark(id) ON DELETE CASCADE,
    state           job_state   NOT NULL DEFAULT 'ready',
    attempts        integer     NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    last_error      text,
    claimed_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- The only query the worker runs often. Partial, so the index is the size of the
-- backlog rather than the corpus.
CREATE INDEX crawl_job_ready_idx ON crawl_job (next_attempt_at)
    WHERE state = 'ready';
```

`bookmark_id` as the primary key, not a job id: one outstanding crawl per URL is the
invariant, and making it the key means the database enforces it rather than the enqueue
code remembering to check. Re-enqueueing is then an upsert:

```sql
INSERT INTO crawl_job (bookmark_id) VALUES (:id)
ON CONFLICT (bookmark_id) DO UPDATE
   SET state = 'ready', next_attempt_at = now()
 WHERE crawl_job.state = 'failed';      -- never disturb one that is running
```

**Claiming, without a race:**

```sql
UPDATE crawl_job SET state = 'running', claimed_at = now(), attempts = attempts + 1
 WHERE bookmark_id IN (
     SELECT bookmark_id FROM crawl_job
      WHERE state = 'ready' AND next_attempt_at <= now()
      ORDER BY next_attempt_at
      LIMIT :n
      FOR UPDATE SKIP LOCKED)
RETURNING bookmark_id;
```

`SKIP LOCKED` is what makes a second worker safe to start, and what makes the answer to
"it is going slowly" be "run another one".

**Enqueue in the same transaction as the upsert.** This is the point of the design, and
it is worth stating plainly: if the enqueue commits with the bookmark, then a crash,
restart or deploy between them is impossible — there is no between. Any fetch that was
owed is still owed after a power cut. Option A's equivalent moment loses the work with no
record that it existed.

**Enqueue only what needs it.** `POST /bookmarks` is an upsert and usually finds an
existing row, so the condition is `fetched_at IS NULL OR fetched_at < now() - :ttl`, not
"on every save".

**Backfill is the same mechanism**, which is the other half of why it earns its place:

```sql
INSERT INTO crawl_job (bookmark_id)
SELECT id FROM bookmark WHERE fetched_at IS NULL
ON CONFLICT DO NOTHING;
```

**What it costs.** A second process to start, supervise and remember. At one user that is
`make worker` in another terminal, or a launchd/systemd unit later; the queue is durable,
so a worker that is not running means the backlog waits, not that saves fail. One more
table, one more enum, one more thing in `schema/create`.

**What it also buys**, once the worker exists as a place to put policy: per-host rate
limiting and politeness, a request timeout and a response size cap, content-type
filtering, and `robots.txt`. None of these can live honestly inside a save request.

**Testing.** The worker is a loop around an injected fetcher, and the fetcher is the only
thing that touches the network. Everything else — claiming, backoff, the failure path,
the "already fetched" skip — is testable against SQLite and Postgres with no network at
all, which is exactly what the in-process design cannot offer.

### What M4 does with it

Not this table. Categorisation has a different payload, a different retry policy and a
different cost per item, and a `job(kind, payload jsonb)` table that serves both is the
shape that becomes a framework nobody wanted. A second small table, `tag_job`, copying
this pattern, is less code than the abstraction that would unify them.

---

## Recommendation

**B2.** Not because the queue is elegant, but because Option A has to grow one anyway at
M4 and will have taught the API to block on the network in the meantime. The honest cost
is a second process; the honest benefit is that saving stays instant, a failed fetch is a
row you can look at, and the backfill that M4 depends on is three lines of SQL rather
than a new subsystem.

The one thing that would change this: if the crawl turns out to be reliably sub-200ms for
the pages you actually save, A's simplicity would be worth revisiting. That is measurable
before committing — and worth measuring, since it is the only real argument against.

## If B2 is chosen, the order of work

1. Confirm pgvector in the running container (above). Nothing else starts until this does.
2. Revision `0002`: `vector` extension, `bookmark_content`, `job_state`, `crawl_job`,
   plus the `schema/create/*.sql` files and the `drop` script, in the same style as `0001`.
   Bump `REQUIRED_SCHEMA_REVISION`, which the existing test will insist on.
3. Enqueue inside the existing upsert transaction, with the `fetched_at` condition. Tests
   first: this is the invariant the whole design rests on.
4. The worker: claim → fetch → extract → store → backoff, with the fetcher injected.
   No embeddings yet.
5. Embeddings as a second pass over `bookmark_content WHERE embedding IS NULL`, so the
   model loads in one process and a re-embed is a `WHERE model <> :current` away.
