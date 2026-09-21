"""The enqueue half of M3.

The crawl queue's whole claim is that a saved bookmark cannot fail to be queued: the job
row is written in the transaction that saves the bookmark, so both commit or neither
does. These tests are that claim, stated in a form that fails when it stops being true.

The worker -- claiming, backoff, fetching -- is tested separately; nothing here touches
the network, because nothing in the save path is allowed to.
"""

from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import select

from bookmarks_api.models import Bookmark, CrawlJob, JobState
from bookmarks_api.routers.bookmarks import _enqueue_crawl, _upsert_bookmark

PAYLOAD = {"url": "https://example.com/an-article"}


def jobs(db):
    return db.execute(select(CrawlJob)).scalars().all()


def test_saving_queues_exactly_one_crawl(client, auth, db):
    client.post("/api/v1/bookmarks", json=PAYLOAD, headers=auth)

    queued = jobs(db)
    assert len(queued) == 1
    assert queued[0].state is JobState.READY
    assert queued[0].attempts == 0


def test_saving_the_same_page_twice_does_not_queue_it_twice(client, auth, db):
    client.post("/api/v1/bookmarks", json=PAYLOAD, headers=auth)
    client.post("/api/v1/bookmarks", json={**PAYLOAD, "tags": ["later"]}, headers=auth)

    assert len(jobs(db)) == 1


def test_a_second_person_saving_it_does_not_queue_it_again(client, auth, other_auth, db):
    """The page is crawled once, not once per saver — the point of the two-level model."""
    client.post("/api/v1/bookmarks", json=PAYLOAD, headers=auth)
    client.post("/api/v1/bookmarks", json=PAYLOAD, headers=other_auth)

    assert len(jobs(db)) == 1


def test_a_re_save_does_not_disturb_a_job_in_flight(client, auth, db):
    """A worker holding the row must not have its attempt count reset under it.

    Re-saving is common — the extension posts on every save sheet — and a job that resets
    to `ready` each time would be handed to a second worker while the first is still
    fetching.
    """
    client.post("/api/v1/bookmarks", json=PAYLOAD, headers=auth)
    job = jobs(db)[0]
    job.state = JobState.RUNNING
    job.attempts = 1
    db.commit()

    client.post("/api/v1/bookmarks", json=PAYLOAD, headers=auth)
    db.expire_all()

    still = jobs(db)[0]
    assert still.state is JobState.RUNNING
    assert still.attempts == 1


def test_an_already_fetched_page_is_not_queued(client, auth, db):
    """Re-saving something crawled last week must not re-crawl the web."""
    client.post("/api/v1/bookmarks", json=PAYLOAD, headers=auth)
    bookmark = db.execute(select(Bookmark)).scalar_one()
    bookmark.fetched_at = datetime.now(UTC)
    for job in jobs(db):
        db.delete(job)
    db.commit()

    client.post("/api/v1/bookmarks", json=PAYLOAD, headers=auth)
    assert jobs(db) == []


def test_the_job_is_written_in_the_callers_transaction(db):
    """The invariant the design rests on: enqueueing commits nothing by itself.

    If `_enqueue_crawl` ever grows a commit — or becomes a background task — this fails,
    because the rollback below would no longer take the job with it. That is exactly the
    regression worth catching: it is invisible in every other test, since they all commit.
    """
    bookmark = _upsert_bookmark(db, "https://example.com/rolled-back")
    _enqueue_crawl(db, bookmark)
    assert len(jobs(db)) == 1, "the job must be visible inside the transaction"

    db.rollback()

    assert jobs(db) == [], "the job outlived the transaction that wrote it"
    assert db.execute(select(Bookmark)).scalars().all() == []


def test_a_failed_save_queues_nothing(client, auth, db):
    """A rejected URL must leave no trace, queue included."""
    r = client.post("/api/v1/bookmarks", json={"url": "   "}, headers=auth)
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert jobs(db) == []
