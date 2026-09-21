"""Test fixtures.

Two suites, deliberately:

*   The **default** suite runs against SQLite in memory. No Docker, no database to start,
    no skips. Everything in `models.py` is plain SQLAlchemy, so the schema builds and the
    route logic -- idempotency, tag intersection, auth -- is exercised for real.
*   The **postgres** suite (`-m postgres`) runs the same routes against a real Postgres
    when `TEST_DATABASE_URL` is set, covering what SQLite cannot: that `alembic upgrade
    head` builds the schema the models describe, and that `UNIQUE (url_hash)` really does
    reject a concurrent duplicate.

A suite that is skipped by default is a suite that rots, so the fast one is the default
and the slow one is opt-in rather than conditional.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bookmarks_api.config import ALEMBIC_INI, Settings, get_settings
from bookmarks_api.db import Base, get_db
from bookmarks_api.main import app

TEST_TOKEN = "test-token-do-not-use-in-anger"  # noqa: S105
SECOND_TOKEN = "second-user-token-for-tests"  # noqa: S105


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite ignores foreign keys unless asked; without this, cascade behaviour in the
    # tests would diverge from Postgres and hide real bugs.
    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def settings() -> Settings:
    """Two tokens, two users.

    Both clients share one `app`, so per-client dependency overrides would clobber each
    other. They differ by the token they send instead -- which is how real clients differ
    anyway, so the test is closer to the thing it is testing.
    """
    return Settings(
        db_user="test",
        db_password="test",
        api_tokens=f"tester:{TEST_TOKEN},someone-else:{SECOND_TOKEN}",
        single_user_id="tester",
    )


@pytest.fixture
def client(db: Session, settings: Settings) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def anon_client(db: Session) -> Iterator[TestClient]:
    """A client whose deployment has no tokens configured -- writes must be refused."""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: Settings(api_tokens="")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def other_client(client: TestClient) -> TestClient:
    """The same app; a different caller is a different token, not a different client."""
    return client


@pytest.fixture
def other_auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {SECOND_TOKEN}"}


@pytest.fixture
def pg_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


# --- Postgres: shared by every -m postgres module -----------------------------------


def alembic_config(url: str):
    from alembic.config import Config

    # Load the shipped alembic.ini and override *only* the URL. Setting script_location
    # here as well would mean the suite never exercises the shipped value -- which is how
    # `script_location = migrations`, resolved against the working directory, stayed
    # broken through a green test run.
    cfg = Config(str(ALEMBIC_INI))
    # The ini is read through configparser, where `%` starts an interpolation: a
    # percent-encoded password or query option would otherwise raise before connecting.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
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
