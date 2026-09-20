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
REQUIRED_SCHEMA_REVISION = "0001"


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

    if found is None:
        raise SchemaMismatch(
            "This database has never been stamped by Alembic, so its schema state is "
            "unknown.\n"
            "If it is the existing v1 database and the M0 migration has NOT been applied:\n"
            "    alembic -c apps/api/alembic.ini upgrade head\n"
            "If the migration was already applied by hand with psql:\n"
            f"    alembic -c apps/api/alembic.ini stamp {required}"
        )

    if found != required:
        raise SchemaMismatch(
            f"Database is at Alembic revision {found}, but this code requires {required}.\n"
            "Run:  alembic -c apps/api/alembic.ini upgrade head\n"
            "If the database is ahead, deploy the matching version of the API instead of "
            "downgrading the schema."
        )
