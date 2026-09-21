# 0012 - The crawl worker

- **Date:** 2026-09-21
- **Status:** Accepted
- **Builds on:** [ADR 0009](0009-crawl-queue-in-postgres.md) (the queue), [ADR 0010](0010-title-seen-at-save.md) (titles), [ADR 0011](0011-conservative-url-normalisation.md) (the URL it fetches)

## Context

ADR 0009 decided that fetching happens in a separate worker that drains `crawl_job`, and revision `0002` built the queue.
Every save now writes a job in its own transaction.
Nothing drains them.
The real database also holds a save made before the queue existed, so it has no job at all.

What the worker produces is what M4 and M6 consume.
Categorisation budgets about 2,000 tokens of extracted text per page (architecture.md section 3), and the embeddings are computed from the same text.
Navigation menus, cookie banners and footers in that text are noise that every later stage pays for, so extraction quality matters more than fetch speed.

This record settles how the worker behaves.
It needs no schema change: `crawl_job`, `bookmark` and `bookmark_content` already have every column it uses.

## Decision

### Shape

- **`python -m bookmarks_api.worker`, run as `make worker`.**
  It lives in the API package because it shares the models, the settings and the URL rules.
  It runs until stopped; `--once` drains what is ready and exits, which is what the tests and a one-off backfill use.
- **One page at a time per worker.**
  More throughput is another worker, which `FOR UPDATE SKIP LOCKED` already makes safe.
  At one user saving a few pages a day, concurrency inside a worker would be machinery with nothing to do.
- **No transaction is held across a network call.**
  Claiming commits before the fetch starts, and the outcome is written in a second, short transaction.
  A slow host then holds a row marked `running`, never a lock.
- **A stop signal finishes the current page and exits.**
  A worker killed outright leaves its job `running`; the lease below recovers it.

### Claiming

```sql
UPDATE crawl_job
   SET state = 'running', claimed_at = now(), attempts = attempts + 1
 WHERE bookmark_id = (
     SELECT bookmark_id FROM crawl_job
      WHERE (state = 'ready' AND next_attempt_at <= now())
         OR (state = 'running' AND claimed_at < now() - interval '10 minutes')
      ORDER BY next_attempt_at
      LIMIT 1
      FOR UPDATE SKIP LOCKED)
RETURNING bookmark_id;
```

**A claim is a ten-minute lease.**
A job still `running` after that belonged to a worker that died, and is claimed again.
No legitimate fetch comes near it: the whole request is capped at 30 seconds.
`attempts` counts claims, so a page that kills its worker every time still runs out of attempts.

### Fetching

- **`httpx`**, already a dependency, synchronous, with TLS verification on.
- **Limits:** connect 10 seconds, whole request 30 seconds, at most 5 redirects, and at most 5 MB of body, read as a stream and abandoned beyond the cap rather than buffered.
- **An honest User-Agent:** `SmartBrowser/<version> (personal bookmark indexer)`.
- **HTML only.**
  The request asks for `text/html` and `application/xhtml+xml`, and anything else is recorded, not extracted.
  PDFs are the main loss: papers get bookmarked.
  Extracting them is its own dependency and its own failure modes, and is deferred rather than refused.
- **Private addresses are refused**, before the request and again at every redirect: loopback, link-local, RFC 1918, unique-local IPv6, and anything else `ipaddress` calls private.
  Every URL the worker fetches was typed or chosen by a user, and once the API serves more than one person, a crawler that fetches `http://169.254.169.254/` or `http://localhost:5432/` on request is a way into the machine it runs on.
  `CRAWL_ALLOW_PRIVATE=true` lifts it for a deployment that wants its intranet pages crawled.
  The check resolves the host itself; a DNS answer that changes between the check and the connection is a known gap, acceptable while the deployment is local.
- **`robots.txt` is not consulted.**
  Each fetch is one page a person chose to save, fetched once, which is what a browser or a link-preview unfurler does, and neither consults it.
  The worker never follows links, so it is not a crawler in the sense `robots.txt` addresses.
- **At most one request per host per second**, per worker.
  Only a backfill ever hits one host repeatedly, and one second keeps that polite without coordinating between workers.

### Extracting

**`trafilatura`**, a new dependency, extracts the main text, the title and the description.
It is built for exactly this: separating an article from the page around it.
Its output is what M4 prompts with and what M6 embeds.

- `bookmark.title` gets the extracted title, whitespace collapsed, capped at 1,024 characters.
  The worker owns that column and every successful crawl overwrites it.
  It is the lowest-ranked title (ADR 0010), so overwriting it never hides anything a person saw or chose.
- `bookmark.description` gets the page's description, from `og:description` or `<meta name="description">`.
- `bookmark_content.text` gets the main text, capped at 200,000 characters.
  The row is upserted: a re-crawl replaces its text and clears `embedding` and `model`, so the embedding pass sees it as new.
- `bookmark.url` is never changed, including after a redirect.
  It is the URL as saved, under ADR 0011's rules; where the page moved to is not what the person saved.

### Outcomes

| The fetch ends in | Job | `bookmark` |
| --- | --- | --- |
| 2xx, HTML | `done` | `fetched_at`, `http_status`, `title`, `description`; content row written |
| 2xx, not HTML | `done`, `last_error` names the type | `fetched_at`, `http_status` |
| 404, 410 | `failed` at once | `http_status` |
| 401, 403 | `failed` at once | `http_status` |
| Other 4xx | `failed` at once | `http_status` |
| 429, 5xx | retried | `http_status` |
| Timeout, connection or TLS error | retried | unchanged |
| Body over 5 MB, private address, too many redirects | `failed` at once | unchanged |

**`fetched_at` means "a fetch succeeded".**
A 404 sets `http_status` and leaves `fetched_at` NULL, so "never fetched" and "fetched and gone" stay distinguishable, as the schema's comment on `http_status` promises.

**Retries back off by a factor of four from one minute**: 1 minute, 4, 16, about an hour, about four hours.
The sixth failed attempt marks the job `failed`, just under six hours after the first.
A `Retry-After` on a 429 or 503 is honoured when it asks for longer, capped at a day.
Every failure writes `last_error` in the far end's words, with the status or exception class first.

**Re-saving a page whose job failed revives the job**: state `ready`, attempts zero, due now.
A person saving a page again is the best evidence there is that it is worth another try.
This changes `_enqueue_crawl`, which today does nothing on a conflict.
It still never touches a job that is `ready`, `running` or `done`.

### Around it

- **`make crawl-backfill`** queues every bookmark with no job and no successful fetch, which is the real database's one save.
  It is an idempotent `INSERT ... SELECT ... ON CONFLICT DO NOTHING`.
- **`make crawl-status`** prints jobs by state and the last ten failures with their errors, so "is it working" is a command rather than SQL.
- **Embeddings are not in the worker.**
  They are the next step: a second pass over `bookmark_content WHERE embedding IS NULL`, so the model loads in one process and never in the fetch loop.

## Options not taken

- **Fetching concurrently inside one worker (asyncio).**
  More throughput than one person's saves will ever need, and more ways to go wrong than the queue's own answer, which is to start another worker.
- **`selectolax` alone for extraction.**
  It is already a dependency and it gets the title and meta tags right.
  It has no notion of main content, so the text would carry every page's navigation and footer into the prompts and the embeddings.
- **Honouring `robots.txt`.**
  Right for a crawler that discovers pages, and wrong for fetching a page a person asked to keep.
  Many sites disallow everything except named search engines, which would leave those saves with no content for no gain.
- **Allowing private addresses by default.**
  Harmless on this machine today, and a server-side request forgery hole on the day a second person gets a token.
  A default that is safe everywhere, plus a setting, costs one line of configuration.
- **Setting `fetched_at` on every completed attempt.**
  One column would then mean both "we have the page" and "we know it is gone".

## Consequences

- A second process to run, as ADR 0009 accepted: `make worker` alongside `make api-dev`.
  If it is not running, saves still work and the backlog waits.
- Pages behind a login, on the private network, or served only as PDF end with no crawled content.
  ADR 0010's saved title still names them.
- The worker is tested without the network: the fetcher is passed in, and a fake one drives every row of the outcomes table.
  The real fetcher is tested against a local HTTP server for the limits, the redirect cap and the private-address refusal.
  Claiming and the lease are Postgres tests with two sessions, because `SKIP LOCKED` is exactly what SQLite cannot show.
- `trafilatura` brings `lxml` and a handful of pure-Python packages into the API environment.
