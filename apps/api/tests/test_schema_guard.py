"""The guard that refuses to run against a mismatched database.

This is the check that converts "500 on one endpoint at 2am" into "the process would not
start, and said why", so its failure messages are asserted, not just its return codes.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from bookmarks_api import schema_guard
from bookmarks_api.schema_guard import REQUIRED_SCHEMA_REVISION, SchemaMismatch, verify

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"


def test_required_revision_matches_alembic_head():
    """The constant the runtime checks must equal the latest migration on disk.

    Without this, adding a migration and forgetting to bump the constant would leave the
    guard silently approving a database that is one revision behind -- exactly the class
    of failure the guard exists to catch.
    """
    revisions, down_revisions = set(), set()
    for path in VERSIONS_DIR.glob("*.py"):
        source = path.read_text()
        for line in source.splitlines():
            if line.startswith("revision: str = "):
                revisions.add(line.split("=", 1)[1].strip().strip('"'))
            if line.startswith("down_revision: str | None = "):
                value = line.split("=", 1)[1].strip().strip('"')
                if value != "None":
                    down_revisions.add(value)

    assert revisions, "no Alembic revisions found"
    heads = revisions - down_revisions
    assert heads == {REQUIRED_SCHEMA_REVISION}, (
        f"Alembic head is {heads}, but REQUIRED_SCHEMA_REVISION is "
        f"{REQUIRED_SCHEMA_REVISION!r} -- bump it in schema_guard.py"
    )


def test_non_postgres_engines_are_skipped():
    """SQLite builds its schema from the models, so Alembic has nothing to say."""
    engine = create_engine("sqlite://")
    verify(engine)  # must not raise
    engine.dispose()


def test_empty_database_explains_both_recovery_paths(monkeypatch):
    engine = create_engine("sqlite://")
    monkeypatch.setattr(engine.dialect, "name", "postgresql")
    monkeypatch.setattr(schema_guard, "current_revision", lambda _: None)

    with pytest.raises(SchemaMismatch) as excinfo:
        verify(engine)

    message = str(excinfo.value)
    assert "no schema" in message
    assert "upgrade head" in message  # the normal case: create it
    assert "stamp" in message  # the recovery case: tables exist, Alembic does not know
    engine.dispose()


def test_behind_database_names_both_revisions(monkeypatch):
    engine = create_engine("sqlite://")
    monkeypatch.setattr(engine.dialect, "name", "postgresql")
    monkeypatch.setattr(schema_guard, "current_revision", lambda _: "0000")

    with pytest.raises(SchemaMismatch) as excinfo:
        verify(engine, required="0007")

    message = str(excinfo.value)
    assert "0000" in message
    assert "0007" in message
    assert "upgrade head" in message
    engine.dispose()


def test_matching_database_passes(monkeypatch):
    engine = create_engine("sqlite://")
    monkeypatch.setattr(engine.dialect, "name", "postgresql")
    monkeypatch.setattr(schema_guard, "current_revision", lambda _: "0001")
    verify(engine, required="0001")
    engine.dispose()


def test_ahead_database_is_also_a_mismatch(monkeypatch):
    """A database ahead of the code is as dangerous as one behind, and must not pass."""
    engine = create_engine("sqlite://")
    monkeypatch.setattr(engine.dialect, "name", "postgresql")
    monkeypatch.setattr(schema_guard, "current_revision", lambda _: "0009")

    with pytest.raises(SchemaMismatch) as excinfo:
        verify(engine, required="0001")
    assert "deploy the matching version" in str(excinfo.value)
    engine.dispose()


def test_errors_name_the_database_they_are_talking_about(monkeypatch):
    """Being pointed at the wrong database is the commonest cause of both errors.

    Without the name in the message you go looking at migrations instead of at your
    connection string -- which is exactly the wrong place.
    """
    engine = create_engine("postgresql+psycopg://u:p@db.example:5432/wrong_one")
    monkeypatch.setattr(schema_guard, "current_revision", lambda _: None)

    with pytest.raises(SchemaMismatch) as excinfo:
        verify(engine)

    message = str(excinfo.value)
    assert "wrong_one" in message
    assert "db.example" in message
    assert "DB_NAME" in message
    engine.dispose()
