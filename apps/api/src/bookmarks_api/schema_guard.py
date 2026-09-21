"""Refuse to run against a database the code does not match.

The worst failure mode in this system is code that expects a column which is not there:
it does not fail at startup, it fails at 2am as a 500 on one endpoint, and the cause is
several layers from the symptom. This turns that into a process that will not boot.

The check is deliberately not a version number. Schema state is *ordinal* -- revision 0007
has either been applied or it has not -- so this compares Alembic revisions and nothing
else. See doc/decisions/0005-versioning-and-compatibility.md.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

# The Alembic revision this code requires. Bump it when adding a migration; the test
# `test_required_revision_matches_alembic_head` fails until you do, so the two cannot
# drift silently.
REQUIRED_SCHEMA_REVISION = "0002"


class SchemaMismatch(RuntimeError):
    """The database is not at the revision this code requires."""


def current_revision(engine: Engine) -> str | None:
    """The revision stamped on *engine*, or None if it has never been stamped."""
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('alembic_version') IS NOT NULL")
        ).scalar()
        if not exists:
            return None
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def verify(engine: Engine, *, required: str = REQUIRED_SCHEMA_REVISION) -> None:
    """Raise :class:`SchemaMismatch` unless the database is at *required*.

    Non-Postgres engines are skipped: the test suite builds its schema directly from the
    models on SQLite, where Alembic has nothing to say.
    """
    if engine.dialect.name != "postgresql":
        return

    found = current_revision(engine)
    # Name the database in both messages. The commonest cause of either is being pointed
    # at the wrong one, and a message that does not say which database it is talking
    # about sends you looking at migrations instead of at your connection string.
    where = f"{engine.url.database!r} on {engine.url.host}:{engine.url.port}"

    if found is None:
        raise SchemaMismatch(
            f"Database {where} has no schema. Create it with:\n"
            "    alembic -c db/alembic.ini upgrade head\n"
            "If the tables exist but Alembic has never recorded a revision for them:\n"
            f"    alembic -c db/alembic.ini stamp {required}\n"
            "If that is not the database you meant, check DB_NAME, DB_HOST and DB_PORT."
        )

    if found != required:
        raise SchemaMismatch(
            f"Database {where} is at Alembic revision {found}, "
            f"but this code requires {required}.\n"
            "Run:  alembic -c db/alembic.ini upgrade head\n"
            "If the database is ahead, deploy the matching version of the API instead of "
            "downgrading the schema."
        )
