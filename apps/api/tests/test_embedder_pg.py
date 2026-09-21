"""The embedding pass against real Postgres and pgvector (ADR 0013).

What SQLite cannot show: that the vectors fit `vector(384)`, that the column's dimension
reads back from the catalog, that the `hnsw` index answers a nearest-neighbour query over
them, and that two embedders take different rows.

Sorts after test_migration_pg.py, whose least-privilege test must run first.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from bookmarks_api import embedder
from bookmarks_api.models import Bookmark, BookmarkContent
from bookmarks_api.urlnorm import url_hash
from conftest import FakeModel

pytestmark = pytest.mark.postgres

T0 = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
PAGES = {
    "https://pg.example/tuning": "Tuning Postgres work memory and shared buffers for sorts",
    "https://pg.example/queues": "Postgres queues with SKIP LOCKED and a transactional enqueue",
    "https://bread.example/": "Sourdough bread with a long cold fermentation in a hot oven",
    "https://bikes.example/": "Motorcycle chain tension and carburettor cleaning",
}


def crawl(session) -> dict[str, int]:
    ids = {}
    for url, body in PAGES.items():
        page = Bookmark(url=url, url_hash=url_hash(url), title=body.split(" with ")[0])
        session.add(page)
        session.flush()
        session.add(BookmarkContent(bookmark_id=page.id, text_=body))
        ids[url] = page.id
    session.commit()
    return ids


def test_the_column_dimension_comes_from_the_catalog(migrated):
    session, _ = migrated
    assert embedder.column_dimension(session) == 384


def test_embedded_pages_are_found_by_nearest_neighbour(migrated):
    session, engine = migrated
    ids = crawl(session)
    written = embedder.run(sessionmaker(bind=engine), FakeModel(), once=True,
                           clock=lambda: T0, log=lambda _: None)
    assert written == len(PAGES)

    with engine.connect() as conn:
        # Force the index, so this is a test of hnsw rather than of a sequential scan.
        conn.execute(text("SET enable_seqscan = off"))
        plan = "\n".join(conn.execute(text(
            "EXPLAIN SELECT bookmark_id FROM bookmark_content "
            "ORDER BY embedding <=> (SELECT embedding FROM bookmark_content "
            "WHERE bookmark_id = :b) LIMIT 2"
        ), {"b": ids["https://pg.example/tuning"]}).scalars())
        nearest = conn.execute(text(
            "SELECT bookmark_id FROM bookmark_content "
            "ORDER BY embedding <=> (SELECT embedding FROM bookmark_content "
            "WHERE bookmark_id = :b) LIMIT 2"
        ), {"b": ids["https://pg.example/tuning"]}).scalars().all()

    assert "bookmark_content_emb_idx" in plan
    assert nearest == [ids["https://pg.example/tuning"], ids["https://pg.example/queues"]]


def test_two_embedders_take_different_rows(migrated):
    session, engine = migrated
    crawl(session)
    factory = sessionmaker(bind=engine)

    holder, other = factory(), factory()
    try:
        # The first embedder's batch, claimed and not yet committed.
        held = holder.execute(
            select(BookmarkContent.bookmark_id)
            .order_by(BookmarkContent.bookmark_id)
            .limit(2)
            .with_for_update(skip_locked=True)
        ).scalars().all()
        other.execute(text("SET lock_timeout = '2s'"))
        taken = embedder.embed_batch(other, FakeModel(), T0)
        assert taken == len(PAGES) - len(held)
        with factory() as check:
            done = check.execute(text(
                "SELECT bookmark_id FROM bookmark_content WHERE embedding IS NOT NULL"
            )).scalars().all()
        assert set(done).isdisjoint(held)
    finally:
        holder.rollback()
        holder.close()
        other.close()
