"""The crawl worker against real Postgres (ADR 0012).

Two things SQLite cannot show: that `SKIP LOCKED` lets a second worker claim beside a
first without waiting, and that the text the worker writes reaches the generated
`tsvector` the search index is built on.

This module sorts after test_migration_pg.py, whose least-privilege test must run before
anything migrates as a superuser; keep new Postgres modules named so that stays true.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from bookmarks_api import worker
from bookmarks_api.fetch import FetchResult
from bookmarks_api.models import Bookmark, CrawlJob, JobState
from bookmarks_api.urlnorm import url_hash

pytestmark = pytest.mark.postgres

ARTICLE = (
    b"<html><head><title>Tuning Postgres</title></head><body><article><p>"
    + b"Work memory is allocated per sort operation, not per query. " * 8
    + b"</p></article></body></html>"
)


def queue(session, *urls: str) -> list[int]:
    ids = []
    for url in urls:
        page = Bookmark(url=url, url_hash=url_hash(url))
        session.add(page)
        session.flush()
        session.add(CrawlJob(bookmark_id=page.id))
        ids.append(page.id)
    session.commit()
    return ids


def soon() -> datetime:
    # The jobs' next_attempt_at defaults to the database's now(), so "due" is judged
    # against the real clock here, not a fixed one.
    return datetime.now(UTC) + timedelta(seconds=1)


def test_a_second_worker_claims_a_different_job_without_waiting(migrated):
    session, engine = migrated
    first, second = queue(session, "https://a.example/", "https://b.example/")
    factory = sessionmaker(bind=engine)

    holder = factory()
    other = factory()
    try:
        # The first worker's claim, not yet committed: its row stays locked.
        held = holder.execute(worker.claim_statement(soon())).scalar_one()
        # Without SKIP LOCKED the second claim would block on that row; the lock timeout
        # turns a block into a failure instead of a hung suite.
        other.execute(text("SET lock_timeout = '2s'"))
        taken = worker.claim(other, soon())
        assert {held, taken} == {first, second}
    finally:
        holder.rollback()
        holder.close()
        other.close()


def test_a_crawled_page_is_searchable_through_the_generated_tsvector(migrated):
    session, engine = migrated
    (bid,) = queue(session, "https://blog.example/pg")
    page = FetchResult(url="https://blog.example/pg", status=200, content_type="text/html",
                       body=ARTICLE)

    class Fetcher:
        def fetch(self, url: str) -> FetchResult:
            return page

    done = worker.run(sessionmaker(bind=engine), Fetcher(), once=True, clock=soon,
                      log=lambda _: None)

    assert done == 1
    with engine.connect() as conn:
        found = conn.execute(text(
            "SELECT bookmark_id FROM bookmark_content "
            "WHERE tsv @@ plainto_tsquery('english', 'allocated sort')"
        )).scalars().all()
        state = conn.execute(
            text("SELECT state FROM crawl_job WHERE bookmark_id = :b"), {"b": bid}
        ).scalar_one()
    assert found == [bid]
    assert state == JobState.DONE.value
