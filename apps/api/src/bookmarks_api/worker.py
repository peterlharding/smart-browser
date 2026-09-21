"""The crawl worker: drain `crawl_job`, one page at a time (ADRs 0009 and 0012).

    uv run python -m bookmarks_api.worker             # run until stopped   (make worker)
    uv run python -m bookmarks_api.worker --once      # drain what is due, then exit
    uv run python -m bookmarks_api.worker backfill    # queue every never-fetched page
    uv run python -m bookmarks_api.worker status      # jobs by state, latest failures

Each page is three short steps, and no transaction spans the network call between them:
*claim* commits a `running` job, *fetch* runs with no transaction open, *record* writes the
outcome. A slow host therefore holds a row marked `running`, never a lock, and a worker
killed mid-fetch leaves a job the ten-minute lease hands to the next claim.

The worker writes `bookmark.title`, `description`, `fetched_at`, `http_status` and
`bookmark_content`, and nothing per save: crawling stays per URL (ADR 0001), and the
crawled title is the lowest-ranked of the three (ADR 0010).
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Update, and_, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from .db import dialect_insert
from .extract import Extracted, extract
from .fetch import Fetcher, FetchResult, HttpxFetcher, Permanent, Transient
from .models import Bookmark, BookmarkContent, CrawlJob, JobState

LEASE = timedelta(minutes=10)
MAX_ATTEMPTS = 6
FIRST_RETRY = timedelta(minutes=1)
RETRY_FACTOR = 4
MAX_RETRY_AFTER = timedelta(days=1)
IDLE_WAIT = 5.0

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


# --- what a fetch means ----------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """What to write for one attempt. `state` READY means "retry"."""

    state: JobState
    error: str | None = None
    http_status: int | None = None
    fetched: bool = False  # sets bookmark.fetched_at: a fetch succeeded
    extracted: Extracted | None = None  # written to bookmark and bookmark_content
    retry_after: float | None = None


def outcome_of(result: FetchResult, url: str) -> Outcome:
    """The ADR 0012 outcomes table, for a fetch that got a response."""
    status = result.status
    if 200 <= status < 300:
        if not result.is_html:
            return Outcome(
                JobState.DONE, f"not html: {result.content_type or 'no content type'}",
                http_status=status, fetched=True,
            )
        try:
            extracted = extract(result.body, result.url or url)
        except Exception as exc:  # noqa: BLE001 - a page that breaks the parser is its outcome
            return Outcome(JobState.FAILED, f"extract: {type(exc).__name__}: {exc}", status)
        return Outcome(JobState.DONE, None, status, fetched=True, extracted=extracted)
    if status == 429 or status >= 500:
        return Outcome(JobState.READY, f"HTTP {status}", status, retry_after=result.retry_after)
    return Outcome(JobState.FAILED, f"HTTP {status}", status)


def attempt(fetcher: Fetcher, url: str) -> Outcome:
    try:
        return outcome_of(fetcher.fetch(url), url)
    except Transient as exc:
        return Outcome(JobState.READY, str(exc))
    except Permanent as exc:
        return Outcome(JobState.FAILED, str(exc))
    except Exception as exc:  # noqa: BLE001
        # A bug, not a verdict on the page. Retried, so it runs out of attempts and shows up
        # in `status` rather than killing the worker on the same job forever.
        traceback.print_exc()
        return Outcome(JobState.READY, f"unexpected {type(exc).__name__}: {exc}")


def retry_delay(attempts: int, retry_after: float | None) -> timedelta:
    """1, 4, 16, 64, 256 minutes; longer if the server asked, up to a day."""
    delay = FIRST_RETRY * RETRY_FACTOR ** (attempts - 1)
    if retry_after is not None:
        delay = max(delay, min(timedelta(seconds=retry_after), MAX_RETRY_AFTER))
    return delay


# --- the queue ---------------------------------------------------------------------


def claim_statement(now: datetime) -> Update:
    """The claim as one statement: pick the next due job, lock it, mark it running.

    `SKIP LOCKED` is what lets a second worker run beside this one: each takes a row the
    other has not locked, and neither waits. SQLite has no row locks and SQLAlchemy drops
    the clause there, which is why the concurrent case is a Postgres test.
    """
    due = or_(
        and_(CrawlJob.state == JobState.READY, CrawlJob.next_attempt_at <= now),
        and_(CrawlJob.state == JobState.RUNNING, CrawlJob.claimed_at < now - LEASE),
    )
    pick = (
        select(CrawlJob.bookmark_id)
        .where(due)
        .order_by(CrawlJob.next_attempt_at, CrawlJob.bookmark_id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    return (
        update(CrawlJob)
        .where(CrawlJob.bookmark_id == pick)
        .values(state=JobState.RUNNING, claimed_at=now, attempts=CrawlJob.attempts + 1)
        .returning(CrawlJob.bookmark_id)
        .execution_options(synchronize_session=False)
    )


def claim(session: Session, now: datetime) -> int | None:
    """Take the next due job, or one whose lease has expired, and commit the claim."""
    claimed = session.execute(claim_statement(now)).scalar_one_or_none()
    session.commit()
    return claimed


def record(session: Session, bookmark_id: int, outcome: Outcome, now: datetime) -> JobState | None:
    """Write *outcome* for a claimed job. None if the bookmark was deleted meanwhile."""
    job = session.get(CrawlJob, bookmark_id)
    bookmark = session.get(Bookmark, bookmark_id)
    if job is None or bookmark is None:
        return None

    if outcome.http_status is not None:
        bookmark.http_status = outcome.http_status
    if outcome.fetched:
        bookmark.fetched_at = now
    if outcome.extracted is not None:
        bookmark.title = outcome.extracted.title
        bookmark.description = outcome.extracted.description
        content = session.get(BookmarkContent, bookmark_id)
        if content is None:
            content = BookmarkContent(bookmark_id=bookmark_id)
            session.add(content)
        # New text means the old embedding describes something else: clearing it is what
        # puts the page back in front of the embedding pass.
        content.text_ = outcome.extracted.text
        content.embedding = None
        content.model = None
        content.updated_at = now

    state, error = outcome.state, outcome.error
    if state is JobState.READY:
        if job.attempts >= MAX_ATTEMPTS:
            state, error = JobState.FAILED, f"{error} (gave up after {job.attempts} attempts)"
        else:
            job.next_attempt_at = now + retry_delay(job.attempts, outcome.retry_after)
    job.state = state
    job.last_error = error
    session.commit()
    return state


def crawl(
    factory: sessionmaker[Session],
    fetcher: Fetcher,
    bookmark_id: int,
    clock: Clock = utcnow,
    log: Callable[[str], None] = print,
) -> JobState | None:
    with factory() as session:
        bookmark = session.get(Bookmark, bookmark_id)
        url = bookmark.url if bookmark is not None else None
    if url is None:
        return None

    outcome = attempt(fetcher, url)  # no transaction open across the network

    with factory() as session:
        state = record(session, bookmark_id, outcome, clock())
    title = outcome.extracted.title if outcome.extracted else None
    detail = outcome.error or repr(title)
    log(f"crawl {bookmark_id} {url} -> {state.value if state else 'deleted'}: {detail}")
    return state


def run(
    factory: sessionmaker[Session],
    fetcher: Fetcher,
    *,
    once: bool = False,
    stop: threading.Event | None = None,
    clock: Clock = utcnow,
    idle: float = IDLE_WAIT,
    log: Callable[[str], None] = print,
) -> int:
    """Claim and crawl until stopped, or with *once* until nothing is due. Returns a count."""
    stop = stop or threading.Event()
    done = 0
    while not stop.is_set():
        with factory() as session:
            bookmark_id = claim(session, clock())
        if bookmark_id is None:
            if once:
                break
            stop.wait(idle)
            continue
        crawl(factory, fetcher, bookmark_id, clock, log)
        done += 1
    return done


# --- around it ---------------------------------------------------------------------


def backfill(session: Session) -> int:
    """Queue every page with no job and no successful fetch. Safe to run any number of times."""
    insert = dialect_insert(session)
    queued = session.execute(
        insert(CrawlJob)
        .from_select(
            [CrawlJob.bookmark_id],
            select(Bookmark.id).where(Bookmark.fetched_at.is_(None)),
        )
        .on_conflict_do_nothing(index_elements=[CrawlJob.bookmark_id])
        .returning(CrawlJob.bookmark_id)
    ).scalars().all()
    session.commit()
    return len(queued)


def status(session: Session, failures: int = 10) -> str:
    counts: dict[JobState, int] = {
        state: count
        for state, count in session.execute(
            select(CrawlJob.state, func.count()).group_by(CrawlJob.state)
        ).tuples()
    }
    lines = ["  ".join(f"{state.value} {counts.get(state, 0)}" for state in JobState)]
    recent = session.execute(
        select(CrawlJob.bookmark_id, CrawlJob.state, CrawlJob.attempts, CrawlJob.last_error,
               Bookmark.url)
        .join(Bookmark, Bookmark.id == CrawlJob.bookmark_id)
        .where(CrawlJob.last_error.is_not(None))
        .order_by(CrawlJob.claimed_at.desc())
        .limit(failures)
    ).all()
    if recent:
        lines.append("latest errors:")
        lines.extend(
            f"  {r.bookmark_id} {r.state.value} after {r.attempts} "
            f"{'attempt' if r.attempts == 1 else 'attempts'}: {r.url}  {r.last_error}"
            for r in recent
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bookmarks_api.worker")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "backfill", "status"])
    parser.add_argument("--once", action="store_true", help="drain what is due, then exit")
    args = parser.parse_args(argv)

    from .config import get_settings
    from .db import get_engine, get_sessionmaker
    from .schema_guard import verify

    settings = get_settings()
    if settings.schema_check:
        verify(get_engine())
    factory = get_sessionmaker()

    if args.command == "backfill":
        with factory() as session:
            print(f"queued {backfill(session)}")
        return 0
    if args.command == "status":
        with factory() as session:
            print(status(session))
        return 0

    stop = threading.Event()

    def finish_then_exit(signum: int, _frame: object) -> None:
        # Finish the page in hand, then exit. A second signal gets the default handler, so
        # an impatient Ctrl-C still stops it at once; the lease recovers that job.
        stop.set()
        signal.signal(signum, signal.SIG_DFL)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, finish_then_exit)
    fetcher = HttpxFetcher(allow_private=settings.crawl_allow_private)
    print(f"worker started; private addresses {'allowed' if fetcher.allow_private else 'refused'}")
    try:
        count = run(factory, fetcher, once=args.once, stop=stop)
    finally:
        fetcher.close()
    print(f"worker stopped after {count} {'page' if count == 1 else 'pages'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
