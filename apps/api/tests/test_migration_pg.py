"""Postgres-only checks.

Opt in with `pytest -m postgres` and `TEST_DATABASE_URL` pointing at a scratch database.
These cover the two things SQLite cannot speak to: that `alembic upgrade head` really
builds the schema the models describe, and that `UNIQUE (url_hash)` is what enforces the
no-duplicates promise rather than the application being careful.

Never point TEST_DATABASE_URL at a real database -- these tests create and drop tables.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from bookmarks_api.schema_guard import REQUIRED_SCHEMA_REVISION, current_revision, verify
from bookmarks_api.urlnorm import url_hash

pytestmark = pytest.mark.postgres

API_ROOT = Path(__file__).resolve().parent.parent
TABLES = [
    "app_user", "user_identity", "bookmark", "user_bookmark",
    "tag", "tag_alias", "bookmark_tag",
]


def alembic_config(url: str):
    from alembic.config import Config

    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture
def migrated(pg_url):
    """A database brought to head by Alembic, torn down afterwards."""
    from alembic import command

    engine = create_engine(pg_url)
    cfg = alembic_config(pg_url)

    command.upgrade(cfg, "head")
    session = sessionmaker(bind=engine)()
    try:
        yield session, engine
    finally:
        session.close()
        command.downgrade(cfg, "base")
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        engine.dispose()


def test_upgrade_creates_every_table(migrated):
    _, engine = migrated
    present = set(inspect(engine).get_table_names())
    assert set(TABLES) <= present


def test_upgrade_stamps_the_revision_the_code_requires(migrated):
    _, engine = migrated
    assert current_revision(engine) == REQUIRED_SCHEMA_REVISION
    verify(engine)  # the guard must be satisfied by a database just brought to head


def test_url_hash_is_unique_at_the_database_level(migrated):
    """The no-duplicates promise, tested where it is actually kept."""
    session, _ = migrated
    digest = url_hash("https://example.com/a")

    session.execute(
        text("INSERT INTO bookmark (url, url_hash) VALUES (:u, :h)"),
        {"u": "https://example.com/a", "h": digest},
    )
    session.commit()

    with pytest.raises(IntegrityError):
        session.execute(
            text("INSERT INTO bookmark (url, url_hash) VALUES (:u, :h)"),
            {"u": "https://example.com/a?spelled=differently", "h": digest},
        )
        session.commit()
    session.rollback()


def test_a_user_cannot_save_the_same_page_twice(migrated):
    session, _ = migrated
    session.execute(text("INSERT INTO app_user (display_name) VALUES ('plh')"))
    session.execute(
        text("INSERT INTO bookmark (url, url_hash) VALUES ('https://x/', :h)"),
        {"h": url_hash("https://x/")},
    )
    session.commit()

    insert = text(
        "INSERT INTO user_bookmark (user_id, bookmark_id) "
        "SELECT u.id, b.id FROM app_user u, bookmark b"
    )
    session.execute(insert)
    session.commit()

    with pytest.raises(IntegrityError):
        session.execute(insert)
        session.commit()
    session.rollback()


def test_blank_tag_names_are_rejected_by_the_check_constraint(migrated):
    """Rejected by the database, not just by the API: one blank tag on 43 bookmarks is
    how a vocabulary decays, and it should be impossible by any route."""
    session, _ = migrated
    with pytest.raises(IntegrityError):
        session.execute(text("INSERT INTO tag (name) VALUES ('   ')"))
        session.commit()
    session.rollback()


def test_deleting_a_save_cascades_to_its_tag_links(migrated):
    session, _ = migrated
    session.execute(text("INSERT INTO app_user (display_name) VALUES ('plh')"))
    session.execute(
        text("INSERT INTO bookmark (url, url_hash) VALUES ('https://x/', :h)"),
        {"h": url_hash("https://x/")},
    )
    session.execute(text("INSERT INTO tag (name) VALUES ('python')"))
    session.execute(
        text("INSERT INTO user_bookmark (user_id, bookmark_id) "
             "SELECT u.id, b.id FROM app_user u, bookmark b")
    )
    session.execute(
        text("INSERT INTO bookmark_tag (user_bookmark_id, tag_id) "
             "SELECT ub.id, t.id FROM user_bookmark ub, tag t")
    )
    session.commit()

    session.execute(text("DELETE FROM user_bookmark"))
    session.commit()
    assert session.execute(text("SELECT count(*) FROM bookmark_tag")).scalar_one() == 0
    # The shared URL record survives; it belongs to everyone.
    assert session.execute(text("SELECT count(*) FROM bookmark")).scalar_one() == 1


def test_downgrade_removes_everything(pg_url):
    from alembic import command

    engine = create_engine(pg_url)
    cfg = alembic_config(pg_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    remaining = set(inspect(engine).get_table_names()) & set(TABLES)
    assert remaining == set()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()
