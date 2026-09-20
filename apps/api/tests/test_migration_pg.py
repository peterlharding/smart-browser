"""Postgres-only checks.

Opt in with `pytest -m postgres` and `TEST_DATABASE_URL` pointing at a scratch database.
These cover what SQLite structurally cannot: sequence detection, advisory-lock id
allocation, and whether `0001_m0_safety.sql` actually applies to a v1-shaped schema.

Never point TEST_DATABASE_URL at the real bookmarks database -- these tests create and
drop tables.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from bookmarks_api.ids import next_id, sequences_installed

pytestmark = pytest.mark.postgres

V1_SCHEMA = """
DROP TABLE IF EXISTS bookmark_tag, bookmark, tag CASCADE;
CREATE TABLE bookmark (
    id integer NOT NULL PRIMARY KEY,
    url character varying(256),
    title character varying(256),
    host character varying(256),
    used timestamp without time zone
);
CREATE TABLE bookmark_tag (
    id integer NOT NULL PRIMARY KEY,
    bookmark_fk integer,
    tag_fk integer
);
CREATE TABLE tag (
    id integer NOT NULL PRIMARY KEY,
    tag character varying(32)
);
"""

MIGRATION = Path(__file__).parent.parent / "migrations" / "sql" / "0001_m0_safety.sql"


@pytest.fixture
def pg_session(pg_url):
    engine = create_engine(pg_url)
    with engine.begin() as conn:
        conn.execute(text(V1_SCHEMA))
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS bookmark_tag, bookmark, tag CASCADE"))
        engine.dispose()


def test_v1_schema_has_no_sequences(pg_session):
    assert sequences_installed(pg_session, "bookmark") is False


def test_advisory_lock_allocation_continues_from_the_maximum(pg_session):
    pg_session.execute(text("INSERT INTO bookmark (id, url) VALUES (7, 'https://x/')"))
    assert next_id(pg_session, "bookmark") == 8
    pg_session.rollback()


def test_allocation_refuses_unknown_tables(pg_session):
    with pytest.raises(ValueError):
        next_id(pg_session, "'; DROP TABLE bookmark; --")


def test_migration_installs_sequences_and_indexes(pg_session):
    sql = MIGRATION.read_text()
    pg_session.execute(text("INSERT INTO bookmark (id, url) VALUES (42, 'https://x/')"))
    pg_session.commit()

    # CREATE INDEX CONCURRENTLY cannot run inside a transaction, so this mirrors how
    # Alembic applies the file: autocommit throughout.
    raw = pg_session.get_bind().raw_connection()
    raw.set_session(autocommit=True)
    with raw.cursor() as cur:
        cur.execute(sql)
    raw.close()

    assert sequences_installed(pg_session, "bookmark") is True

    # The next insert must not collide with the existing row.
    pg_session.execute(text("INSERT INTO bookmark (url) VALUES ('https://y/')"))
    pg_session.commit()
    highest = pg_session.execute(text("SELECT MAX(id) FROM bookmark")).scalar_one()
    assert highest == 43

    indexes = {
        row[0]
        for row in pg_session.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename IN "
                 "('bookmark','bookmark_tag')")
        )
    }
    assert "bookmark_tag_tag_fk_idx" in indexes
    assert "bookmark_url_idx" in indexes


def test_alembic_upgrade_and_downgrade_round_trip(pg_url, pg_session):
    """`alembic upgrade head` must work end to end, not just the raw SQL.

    Applying the .sql file by hand and calling that a tested migration would miss the
    parts Alembic owns: the transaction boundary, the autocommit block around
    CONCURRENTLY, and the version stamp the schema guard reads.
    """
    from alembic import command
    from alembic.config import Config

    from bookmarks_api.schema_guard import REQUIRED_SCHEMA_REVISION, current_revision, verify

    api_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", pg_url)

    engine = pg_session.get_bind()

    command.upgrade(cfg, "head")
    assert current_revision(engine) == REQUIRED_SCHEMA_REVISION

    # The guard must be satisfied by a database Alembic has just brought to head.
    verify(engine)

    # And the sequences it installed must actually allocate.
    pg_session.execute(text("INSERT INTO bookmark (url) VALUES ('https://after-upgrade/')"))
    pg_session.commit()

    command.downgrade(cfg, "base")
    assert current_revision(engine) in (None, "")
