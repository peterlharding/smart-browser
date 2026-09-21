"""Engine and session handling.

The engine is created on first use rather than at import. Importing this module must not
require a working configuration -- the test suite builds its own engine, and `alembic`
needs to import the app to read settings before it has a database to talk to.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
        pool_timeout=20,
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)


def dialect_insert(session: Session):
    """`INSERT ... ON CONFLICT` for whichever backend *session* is bound to.

    Postgres in production, SQLite in the default test suite; both spell the conflict
    clause the same way through their own dialect's `insert`.
    """
    bind = session.get_bind()
    return sqlite_insert if bind.dialect.name == "sqlite" else pg_insert


def get_db() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
