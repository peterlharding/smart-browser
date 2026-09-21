"""The crawl worker (ADR 0012), with a fake fetcher and no network.

Saves go through the API, so each job is queued exactly as a real save queues it. Time is
a parameter, so backoff and the lease are tested by moving a clock rather than waiting.
The concurrent claim is a Postgres test: SQLite has no row locks for SKIP LOCKED to skip.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from bookmarks_api import worker
from bookmarks_api.fetch import FetchResult, Permanent, Transient
from bookmarks_api.models import Bookmark, BookmarkContent, CrawlJob, JobState

# "Now", for the worker. Jobs get next_attempt_at from the real clock when they are saved,
# so T0 must be after that: an hour ahead of the run. It was once a fixed date, and every
# test that claims a job failed from noon on that day on, when real time overtook it.
T0 = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)
ARTICLE = (
    b"<html><head><title>Tuning Postgres</title>"
    b'<meta name="description" content="Make it fast."></head><body><article>'
    + b"<p>" + b"Work memory is allocated per sort operation, not per query. " * 8 + b"</p>"
    + b"</article></body></html>"
)


class FakeFetcher:
    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        assert isinstance(answer, FetchResult)
        return answer


def html(url: str, body: bytes = ARTICLE, status: int = 200) -> FetchResult:
    return FetchResult(url=url, status=status, content_type="text/html", body=body)


def status_only(url: str, status: int, retry_after: float | None = None) -> FetchResult:
    return FetchResult(
        url=url, status=status, content_type="text/html", body=b"", retry_after=retry_after
    )


@pytest.fixture
def factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def save(client, auth, url: str, **extra) -> dict:
    return client.post("/api/v1/bookmarks", json={"url": url, **extra}, headers=auth).json()


def job(factory, bookmark_id: int) -> CrawlJob:
    with factory() as session:
        return session.get(CrawlJob, bookmark_id)


def page(factory, bookmark_id: int) -> Bookmark:
    with factory() as session:
        return session.get(Bookmark, bookmark_id)


def bookmark_id_of(factory, url: str) -> int:
    with factory() as session:
        return session.execute(select(Bookmark.id).where(Bookmark.url == url)).scalar_one()


def run_once(factory, fetcher, at: datetime = T0) -> int:
    return worker.run(factory, fetcher, once=True, clock=lambda: at, log=lambda _: None)


# --- success -------------------------------------------------------------------------


def test_a_saved_page_is_fetched_extracted_and_stored(client, auth, factory):
    url = "https://blog.example/pg"
    save(client, auth, url)
    assert run_once(factory, FakeFetcher({url: html(url)})) == 1

    bid = bookmark_id_of(factory, url)
    assert job(factory, bid).state is JobState.DONE
    stored = page(factory, bid)
    assert (stored.title, stored.description, stored.http_status) == (
        "Tuning Postgres", "Make it fast.", 200,
    )
    assert stored.fetched_at is not None
    with factory() as session:
        content = session.get(BookmarkContent, bid)
    assert "allocated per sort operation" in content.text_


def test_the_crawled_title_reaches_a_save_that_sent_none(client, auth, factory):
    """ADR 0010's third title, for a link saved from the context menu."""
    url = "https://blog.example/pg"
    saved = save(client, auth, url)
    assert saved["title"] is None

    run_once(factory, FakeFetcher({url: html(url)}))

    got = client.get(f"/api/v1/bookmarks/{saved['id']}", headers=auth).json()
    assert got["title"] == "Tuning Postgres"


def test_the_crawled_title_never_hides_the_one_seen(client, auth, factory):
    url = "https://mail.example/inbox"
    saved = save(client, auth, url, title="Inbox (3)")
    run_once(factory, FakeFetcher({url: html(url, b"<html><head><title>Sign in</title>")}))

    got = client.get(f"/api/v1/bookmarks/{saved['id']}", headers=auth).json()
    assert got["title"] == "Inbox (3)"


def test_a_non_html_page_is_done_with_the_type_recorded(client, auth, factory):
    url = "https://papers.example/a.pdf"
    save(client, auth, url)
    pdf = FetchResult(url=url, status=200, content_type="application/pdf", body=b"")
    run_once(factory, FakeFetcher({url: pdf}))

    bid = bookmark_id_of(factory, url)
    assert (job(factory, bid).state, job(factory, bid).last_error) == (
        JobState.DONE, "not html: application/pdf",
    )
    assert page(factory, bid).fetched_at is not None


def test_a_page_that_was_already_fetched_is_not_fetched_again(client, auth, factory):
    url = "https://blog.example/pg"
    save(client, auth, url)
    fetcher = FakeFetcher({url: html(url)})
    run_once(factory, fetcher)
    save(client, auth, url)
    run_once(factory, fetcher)
    assert fetcher.calls == [url]


# --- failure -------------------------------------------------------------------------


@pytest.mark.parametrize("code", [401, 403, 404, 410, 451])
def test_a_client_error_fails_at_once_and_keeps_the_status(client, auth, factory, code):
    url = "https://gone.example/"
    save(client, auth, url)
    run_once(factory, FakeFetcher({url: status_only(url, code)}))

    bid = bookmark_id_of(factory, url)
    assert (job(factory, bid).state, job(factory, bid).last_error) == (
        JobState.FAILED, f"HTTP {code}",
    )
    stored = page(factory, bid)
    assert stored.http_status == code
    assert stored.fetched_at is None, "fetched_at means a fetch succeeded"


@pytest.mark.parametrize(
    "error", [Permanent("private address: x resolves to 10.0.0.1"), Permanent("body over 5 MB")]
)
def test_a_permanent_error_fails_at_once(client, auth, factory, error):
    url = "https://x.example/"
    save(client, auth, url)
    run_once(factory, FakeFetcher({url: error}))

    assert job(factory, bookmark_id_of(factory, url)).state is JobState.FAILED


@pytest.mark.parametrize(
    "answer",
    [
        status_only("https://x.example/", 503),
        status_only("https://x.example/", 429),
        Transient("timeout: ReadTimeout"),
        Transient("ConnectError: refused"),
    ],
)
def test_a_transient_failure_is_retried_later(client, auth, factory, answer):
    url = "https://x.example/"
    save(client, auth, url)
    run_once(factory, FakeFetcher({url: answer}))

    queued = job(factory, bookmark_id_of(factory, url))
    assert queued.state is JobState.READY
    assert queued.next_attempt_at.replace(tzinfo=UTC) == T0 + timedelta(minutes=1)


def test_retries_back_off_by_four_then_give_up(client, auth, factory):
    url = "https://x.example/"
    save(client, auth, url)
    fetcher = FakeFetcher({url: status_only(url, 503)})
    bid = bookmark_id_of(factory, url)

    at, gaps = T0, []
    for _ in range(5):
        run_once(factory, fetcher, at)
        due = job(factory, bid).next_attempt_at.replace(tzinfo=UTC)
        gaps.append(due - at)
        assert run_once(factory, fetcher, due - timedelta(seconds=1)) == 0, "not before it is due"
        at = due
    run_once(factory, fetcher, at)

    assert gaps == [timedelta(minutes=m) for m in (1, 4, 16, 64, 256)]
    final = job(factory, bid)
    assert final.state is JobState.FAILED
    assert final.attempts == 6
    assert final.last_error == "HTTP 503 (gave up after 6 attempts)"


def test_retry_after_is_honoured_when_longer_and_capped_at_a_day(client, auth, factory):
    for url, asked, expected in [
        ("https://a.example/", 30, timedelta(minutes=1)),
        ("https://b.example/", 7200, timedelta(hours=2)),
        ("https://c.example/", 10 * 86400, timedelta(days=1)),
    ]:
        save(client, auth, url)
        run_once(factory, FakeFetcher({url: status_only(url, 429, retry_after=asked)}))
        due = job(factory, bookmark_id_of(factory, url)).next_attempt_at.replace(tzinfo=UTC)
        assert due - T0 == expected, url


def test_a_bug_in_the_fetcher_is_retried_not_fatal(client, auth, factory, capsys):
    url = "https://x.example/"
    save(client, auth, url)
    run_once(factory, FakeFetcher({url: RuntimeError("boom")}))

    queued = job(factory, bookmark_id_of(factory, url))
    assert (queued.state, queued.last_error) == (JobState.READY, "unexpected RuntimeError: boom")
    assert "RuntimeError: boom" in capsys.readouterr().err


def test_resaving_a_failed_page_revives_its_job(client, auth, factory):
    url = "https://gone.example/"
    save(client, auth, url)
    run_once(factory, FakeFetcher({url: status_only(url, 404)}))
    bid = bookmark_id_of(factory, url)
    assert job(factory, bid).state is JobState.FAILED

    save(client, auth, url)

    revived = job(factory, bid)
    assert (revived.state, revived.attempts, revived.last_error) == (JobState.READY, 0, None)


def test_resaving_leaves_a_waiting_retry_alone(client, auth, factory):
    url = "https://x.example/"
    save(client, auth, url)
    run_once(factory, FakeFetcher({url: status_only(url, 503)}))
    bid = bookmark_id_of(factory, url)
    before = job(factory, bid)

    save(client, auth, url)

    after = job(factory, bid)
    assert (after.state, after.attempts, after.next_attempt_at) == (
        before.state, before.attempts, before.next_attempt_at,
    )


# --- the lease -----------------------------------------------------------------------


def test_a_job_abandoned_by_a_dead_worker_is_claimed_again_after_the_lease(client, auth, factory):
    url = "https://x.example/"
    save(client, auth, url)
    bid = bookmark_id_of(factory, url)
    with factory() as session:
        assert worker.claim(session, T0) == bid  # and then the worker dies

    with factory() as session:
        assert worker.claim(session, T0 + timedelta(minutes=9)) is None, "still leased"
    with factory() as session:
        assert worker.claim(session, T0 + timedelta(minutes=11)) == bid
    assert job(factory, bid).attempts == 2, "a page that kills its worker still runs out"


def test_a_page_deleted_mid_crawl_is_skipped(client, auth, factory):
    url = "https://x.example/"
    save(client, auth, url)
    bid = bookmark_id_of(factory, url)
    with factory() as session:
        worker.claim(session, T0)
        session.delete(session.get(Bookmark, bid))
        session.commit()

    outcome = worker.Outcome(JobState.DONE, http_status=200, fetched=True)
    with factory() as session:
        assert worker.record(session, bid, outcome, T0) is None


# --- around it -----------------------------------------------------------------------


def test_backfill_queues_what_was_saved_before_the_queue(client, auth, factory):
    url = "https://old.example/"
    save(client, auth, url)
    bid = bookmark_id_of(factory, url)
    with factory() as session:
        session.delete(session.get(CrawlJob, bid))  # as if saved before revision 0002
        session.commit()

    with factory() as session:
        assert worker.backfill(session) == 1
    with factory() as session:
        assert worker.backfill(session) == 0, "idempotent"
    assert job(factory, bid).state is JobState.READY


def test_backfill_skips_pages_already_fetched(client, auth, factory):
    url = "https://blog.example/pg"
    save(client, auth, url)
    run_once(factory, FakeFetcher({url: html(url)}))
    with factory() as session:
        session.delete(session.get(CrawlJob, bookmark_id_of(factory, url)))
        session.commit()
    with factory() as session:
        assert worker.backfill(session) == 0


def test_status_counts_jobs_and_shows_the_latest_errors(client, auth, factory):
    save(client, auth, "https://ok.example/")
    save(client, auth, "https://gone.example/")
    save(client, auth, "https://waiting.example/")
    run_once(
        factory,
        FakeFetcher({
            "https://ok.example/": html("https://ok.example/"),
            "https://gone.example/": status_only("https://gone.example/", 404),
            "https://waiting.example/": Transient("timeout: ReadTimeout"),
        }),
    )

    with factory() as session:
        text = worker.status(session)
    assert text.splitlines()[0] == "ready 1  running 0  done 1  failed 1"
    assert "https://gone.example/  HTTP 404" in text
    assert "https://waiting.example/  timeout: ReadTimeout" in text
