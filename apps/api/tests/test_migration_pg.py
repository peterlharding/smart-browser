"""Postgres-only checks.

Opt in with `pytest -m postgres` and `TEST_DATABASE_URL` pointing at a scratch database.
These cover the two things SQLite cannot speak to: that `alembic upgrade head` really
builds the schema the models describe, and that `UNIQUE (url_hash)` is what enforces the
no-duplicates promise rather than the application being careful.

Never point TEST_DATABASE_URL at a real database -- these tests create and drop tables.
"""


import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from bookmarks_api.config import ALEMBIC_INI, MIGRATIONS_DIR
from bookmarks_api.schema_guard import REQUIRED_SCHEMA_REVISION, current_revision, verify
from bookmarks_api.urlnorm import url_hash

pytestmark = pytest.mark.postgres


TABLES = [
    "app_user", "user_identity", "bookmark", "user_bookmark",
    "tag", "tag_alias", "bookmark_tag",
]


def alembic_config(url: str):
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
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
    """The behavioural half of the env.py transaction guard.

    A migration that executes anything on its own connection before context.configure()
    is rolled back on close while still logging success and exiting 0, so "alembic said
    it worked" proves nothing. This is what proves it. SQLite cannot stand in: alembic
    uses non-transactional DDL there and commits regardless.
    """
    _, engine = migrated
    present = set(inspect(engine).get_table_names())
    missing = set(TABLES) - present
    assert not missing, (
        f"upgrade reported success but {sorted(missing)} are absent -- "
        f"the migration was almost certainly rolled back, see test_migration_env.py"
    )


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


# --- the two sources of truth must agree ------------------------------------


def test_sql_files_and_models_describe_the_same_schema(pg_url, migrated):
    """The schema is now stated twice: in db/schema/create/*.sql and in models.py.

    Both are deliberate -- the SQL is what runs, the models are what the ORM and the
    SQLite test suite use -- but two sources of truth drift, silently, and the failure
    surfaces as a query that works in tests and breaks in production. This diffs them.

    It caught three real differences when the SQL files were introduced: `is_active`,
    `visit_count` and `source` had Python-side defaults in the models and server defaults
    in the SQL. A Python default only applies when the ORM does the insert, so raw SQL and
    `INSERT ... ON CONFLICT` would have written NULL into NOT NULL columns.
    """
    from sqlalchemy import create_engine, inspect

    from bookmarks_api.db import Base

    session, migrated_engine = migrated

    mirror_url = pg_url.rsplit("/", 1)[0] + "/page_history_models_mirror"
    admin = create_engine(pg_url.replace("+psycopg", "+psycopg"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS page_history_models_mirror"))
        conn.execute(text("CREATE DATABASE page_history_models_mirror"))
    admin.dispose()

    mirror = create_engine(mirror_url)
    try:
        Base.metadata.create_all(mirror)
        differences = _diff(inspect(migrated_engine), inspect(mirror))
    finally:
        mirror.dispose()
        admin = create_engine(pg_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS page_history_models_mirror"))
        admin.dispose()

    assert not differences, "SQL files and models disagree:\n  " + "\n  ".join(differences)


def _fk_key(fk: dict) -> tuple:
    return (
        tuple(fk["constrained_columns"]),
        fk["referred_table"],
        tuple(fk["referred_columns"]),
        (fk.get("options") or {}).get("ondelete"),
    )


def _diff(from_sql, from_models) -> list[str]:
    """Structural differences between two inspected schemas, as readable lines."""
    out: list[str] = []

    sql_tables = set(from_sql.get_table_names()) - {"alembic_version"}
    model_tables = set(from_models.get_table_names())
    for name in sorted(sql_tables - model_tables):
        out.append(f"table {name}: in the SQL files but not the models")
    for name in sorted(model_tables - sql_tables):
        out.append(f"table {name}: in the models but not the SQL files")

    for table in sorted(sql_tables & model_tables):
        a = {c["name"]: c for c in from_sql.get_columns(table)}
        b = {c["name"]: c for c in from_models.get_columns(table)}
        for column in sorted(a.keys() | b.keys()):
            if column not in a:
                out.append(f"{table}.{column}: only in the models")
                continue
            if column not in b:
                out.append(f"{table}.{column}: only in the SQL files")
                continue
            for attr in ("type", "nullable"):
                if str(a[column][attr]) != str(b[column][attr]):
                    out.append(
                        f"{table}.{column} {attr}: sql={a[column][attr]!s} "
                        f"models={b[column][attr]!s}"
                    )
            # Strip the cast Postgres adds when reflecting, so 'user'::tag_source and
            # 'user' compare equal.
            da = (a[column].get("default") or "").split("::")[0].strip("'")
            db_ = (b[column].get("default") or "").split("::")[0].strip("'")
            if da != db_:
                out.append(f"{table}.{column} default: sql={da!r} models={db_!r}")

        if (
            from_sql.get_pk_constraint(table)["constrained_columns"]
            != from_models.get_pk_constraint(table)["constrained_columns"]
        ):
            out.append(f"{table}: primary key differs")

        ua = sorted(tuple(u["column_names"]) for u in from_sql.get_unique_constraints(table))
        ub = sorted(tuple(u["column_names"]) for u in from_models.get_unique_constraints(table))
        if ua != ub:
            out.append(f"{table}: unique constraints sql={ua} models={ub}")

        fa = sorted(_fk_key(f) for f in from_sql.get_foreign_keys(table))
        fb = sorted(_fk_key(f) for f in from_models.get_foreign_keys(table))
        if fa != fb:
            out.append(f"{table}: foreign keys sql={fa} models={fb}")

    return out
