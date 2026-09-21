"""Postgres-only checks.

Opt in with `pytest -m postgres` and `TEST_DATABASE_URL` pointing at a scratch database.
These cover the two things SQLite cannot speak to: that `alembic upgrade head` really
builds the schema the models describe, and that `UNIQUE (url_hash)` is what enforces the
no-duplicates promise rather than the application being careful.

Never point TEST_DATABASE_URL at a real database -- these tests create and drop tables.
"""


import pytest
from sqlalchemy import create_engine, inspect, make_url, text
from sqlalchemy.exc import IntegrityError

from bookmarks_api.config import ALEMBIC_INI
from bookmarks_api.schema_guard import REQUIRED_SCHEMA_REVISION, current_revision, verify
from bookmarks_api.urlnorm import url_hash
from conftest import alembic_config

pytestmark = pytest.mark.postgres


TABLES = [
    "app_user", "user_identity", "bookmark", "user_bookmark",
    "tag", "tag_alias", "bookmark_tag",
    "bookmark_content", "crawl_job",
]

# Columns the SQL files define and the models deliberately do not. `tsv` is a Postgres
# generated tsvector: there is no SQLite equivalent, nothing in the ORM reads it, and
# search will be raw SQL over the GIN index. Listing it here keeps the diff strict about
# everything else -- an unlisted difference is still a failure.
SQL_ONLY = {("bookmark_content", "tsv")}


# --- the application role is not a superuser --------------------------------
#
# First in the module, deliberately: pytest runs a module's tests in definition order, and
# every test below connects as whoever TEST_DATABASE_URL names -- a superuser in CI. Once
# one of them has run the migrations, anything the migrations leave behind outside the
# tables they drop (an extension created with IF NOT EXISTS, say) is already there, and
# this test would pass by finding it rather than by being allowed to create it. Moved
# here after exactly that: a superuser-only CREATE EXTENSION slipped past it when it ran
# last.

LEAST_PRIVILEGED = "sb_least_privilege"


def _drop_role(conn, role: str) -> None:
    # DROP OWNED first: a role that still owns tables from an interrupted run cannot be
    # dropped, and the next run would then fail on CREATE ROLE rather than on anything
    # this test is about.
    conn.execute(text(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE 'DROP OWNED BY {role}';
                EXECUTE 'DROP ROLE {role}';
            END IF;
        END
        $$
    """))


@pytest.fixture
def least_privileged_url(pg_url):
    """A URL whose connections act as a role with no special privileges.

    A superuser connection -- CI's `postgres`, or any local role that happens to be one --
    passes every privilege check, so a suite run through it cannot see a migration that
    needs one. From a superuser, this creates a throwaway role holding exactly what an
    application role holds (it may create objects in `public`, as the database owner may)
    and has every connection switch to it with `-c role=`. Postgres then checks privileges
    against that role, and the tables it creates are owned by it, as they would be by
    `api`.

    From a connection that is not a superuser there is nothing to switch to and nothing
    to create a role with, and none is needed: that role *is* the deployment shape, and
    the test checks its privileges instead of assuming them.
    """
    admin = create_engine(pg_url)
    with admin.connect() as conn:
        superuser = conn.execute(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        ).scalar_one()
    if not superuser:
        admin.dispose()
        yield pg_url
        return

    with admin.begin() as conn:
        _drop_role(conn, LEAST_PRIVILEGED)
        conn.execute(text(
            f"CREATE ROLE {LEAST_PRIVILEGED} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOREPLICATION NOBYPASSRLS"
        ))
        conn.execute(text(f"GRANT USAGE, CREATE ON SCHEMA public TO {LEAST_PRIVILEGED}"))

    url = (
        make_url(pg_url)
        .update_query_dict({"options": f"-c role={LEAST_PRIVILEGED}"})
        .render_as_string(hide_password=False)
    )
    try:
        yield url
    finally:
        with admin.begin() as conn:
            conn.execute(text(f"REVOKE ALL ON SCHEMA public FROM {LEAST_PRIVILEGED}"))
            _drop_role(conn, LEAST_PRIVILEGED)
        admin.dispose()


def test_the_schema_needs_no_special_privileges(least_privileged_url):
    """Migrate, use pgvector and tear down as a role that is not a superuser.

    The claim this checks is in ADR 0009 and the plan: pgvector needs a superuser exactly
    once, in `make db-bootstrap`, and everything after that runs as the application role.
    Until this test, nothing checked it. Every other Postgres test connects as whoever
    `TEST_DATABASE_URL` names, which is `postgres` in CI and was a superuser `api`
    locally, so a migration needing a privilege the real role lacks would have passed
    everywhere it was tested.
    """
    from alembic import command

    engine = create_engine(least_privileged_url)
    cfg = alembic_config(least_privileged_url)

    with engine.connect() as conn:
        role, is_super, createdb, createrole = conn.execute(text(
            "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole "
            "FROM pg_roles WHERE rolname = current_user"
        )).one()
    assert not (is_super or createdb or createrole), (
        f"{role!r} is SUPERUSER, CREATEDB or CREATEROLE, so this test proves nothing. "
        "The application role needs none of them: see ADR 0009."
    )

    command.upgrade(cfg, "head")
    try:
        with engine.begin() as conn:
            owners = set(conn.execute(
                text("SELECT tableowner FROM pg_tables WHERE tablename = ANY(:t)"),
                {"t": TABLES},
            ).scalars())
            assert owners == {role}, f"tables owned by {owners}, expected {role!r}"

            # Past the migration, the extension is used, not administered: the vector
            # type, the hnsw index and the distance operator all belong to PUBLIC.
            bookmark_id = conn.execute(
                text("INSERT INTO bookmark (url, url_hash) VALUES (:u, :h) RETURNING id"),
                {"u": "https://example.com/", "h": url_hash("https://example.com/")},
            ).scalar_one()
            conn.execute(text("INSERT INTO crawl_job (bookmark_id) VALUES (:b)"),
                         {"b": bookmark_id})
            vector = "[" + ",".join(["0.1"] * 384) + "]"
            conn.execute(
                text("INSERT INTO bookmark_content (bookmark_id, text, embedding) "
                     "VALUES (:b, 'hello world', CAST(:v AS vector))"),
                {"b": bookmark_id, "v": vector},
            )
            nearest = conn.execute(
                text("SELECT bookmark_id FROM bookmark_content "
                     "ORDER BY embedding <=> CAST(:v AS vector) LIMIT 1"),
                {"v": vector},
            ).scalar_one()
            assert nearest == bookmark_id
    finally:
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


def test_0003_moves_titles_seen_out_of_the_override_and_back(pg_url):
    """Every override before 0003 was a tab title written by a client (ADR 0010).

    Up, it moves to saved_title and the override is cleared. Down, it goes back, and where
    a save has both, the override -- the one a person chose -- is the one kept.
    """
    from alembic import command

    engine = create_engine(pg_url)
    cfg = alembic_config(pg_url)
    command.upgrade(cfg, "0002")
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO app_user (display_name) VALUES ('plh')"))
            for n, override in ((1, "Seen in the tab"), (2, None)):
                url = f"https://example.com/{n}"
                conn.execute(
                    text("INSERT INTO bookmark (url, url_hash) VALUES (:u, :h)"),
                    {"u": url, "h": url_hash(url)},
                )
                conn.execute(
                    text("INSERT INTO user_bookmark (user_id, bookmark_id, title_override) "
                         "SELECT u.id, b.id, :t FROM app_user u, bookmark b WHERE b.url = :u"),
                    {"t": override, "u": url},
                )

        def titles():
            with engine.connect() as conn:
                return conn.execute(text(
                    "SELECT b.url, ub.title_override, ub.saved_title FROM user_bookmark ub "
                    "JOIN bookmark b ON b.id = ub.bookmark_id ORDER BY b.url"
                )).all()

        command.upgrade(cfg, "0003")
        assert titles() == [
            ("https://example.com/1", None, "Seen in the tab"),
            ("https://example.com/2", None, None),
        ]

        # A person now chooses a title for the second save, which also has one seen.
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE user_bookmark SET title_override = 'Mine', saved_title = 'Seen' "
                "WHERE bookmark_id = (SELECT id FROM bookmark WHERE url LIKE '%/2')"
            ))

        command.downgrade(cfg, "0002")
        with engine.connect() as conn:
            restored = conn.execute(text(
                "SELECT b.url, ub.title_override FROM user_bookmark ub "
                "JOIN bookmark b ON b.id = ub.bookmark_id ORDER BY b.url"
            )).all()
        assert restored == [
            ("https://example.com/1", "Seen in the tab"),
            ("https://example.com/2", "Mine"),
        ]
    finally:
        command.downgrade(cfg, "base")
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        engine.dispose()


# --- the two sources of truth must agree ------------------------------------

MIRROR_SCHEMA = "models_mirror"


def test_sql_files_and_models_describe_the_same_schema(pg_url, migrated):
    """The schema is now stated twice: in db/schema/create/*.sql and in models.py.

    Both are deliberate -- the SQL is what runs, the models are what the ORM and the
    SQLite test suite use -- but two sources of truth drift, silently, and the failure
    surfaces as a query that works in tests and breaks in production. This diffs them.

    It caught three real differences when the SQL files were introduced: `is_active`,
    `visit_count` and `source` had Python-side defaults in the models and server defaults
    in the SQL. A Python default only applies when the ORM does the insert, so raw SQL and
    `INSERT ... ON CONFLICT` would have written NULL into NOT NULL columns.

    The models are built into a second *schema* of the same database rather than a second
    database. `CREATE DATABASE` needs the CREATEDB privilege, which an application role
    has no business holding -- the first run of this suite against a realistic `api` role
    failed on exactly that. `CREATE SCHEMA` needs only rights the database owner has.
    """
    from bookmarks_api.db import Base

    _, migrated_engine = migrated

    mirror = create_engine(pg_url)
    try:
        with mirror.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {MIRROR_SCHEMA} CASCADE"))
            conn.execute(text(f"CREATE SCHEMA {MIRROR_SCHEMA}"))

        # schema_translate_map rewrites every unqualified name in the metadata into the
        # mirror schema, for DDL as well as queries, so models.py needs no test-only
        # knowledge of this. That includes the `tag_source` enum: the mirror gets its own
        # `models_mirror.tag_source` rather than colliding with the one the migration
        # created in public, and DROP SCHEMA CASCADE takes it away again.
        with mirror.connect().execution_options(
            schema_translate_map={None: MIRROR_SCHEMA}
        ) as conn:
            Base.metadata.create_all(conn)
            conn.commit()

        differences = _diff(
            _InSchema(inspect(migrated_engine)),
            _InSchema(inspect(mirror), MIRROR_SCHEMA),
        )
    finally:
        with mirror.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {MIRROR_SCHEMA} CASCADE"))
        mirror.dispose()

    assert not differences, "SQL files and models disagree:\n  " + "\n  ".join(differences)


class _InSchema:
    """An inspector bound to one schema, so `_diff` can treat both sides alike.

    Without this the two halves of the comparison would be asymmetric -- one passing
    `schema=` everywhere and one not -- which is how a test ends up quietly inspecting
    the wrong schema and passing.
    """

    def __init__(self, inspector, schema: str | None = None) -> None:
        self._inspector = inspector
        self._schema = schema

    def get_table_names(self) -> list[str]:
        return self._inspector.get_table_names(schema=self._schema)

    def get_columns(self, table: str) -> list[dict]:
        return self._inspector.get_columns(table, schema=self._schema)

    def get_pk_constraint(self, table: str) -> dict:
        return self._inspector.get_pk_constraint(table, schema=self._schema)

    def get_unique_constraints(self, table: str) -> list[dict]:
        return self._inspector.get_unique_constraints(table, schema=self._schema)

    def get_foreign_keys(self, table: str) -> list[dict]:
        return self._inspector.get_foreign_keys(table, schema=self._schema)


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
            if (table, column) in SQL_ONLY:
                if column not in a:
                    out.append(f"{table}.{column}: listed as SQL-only but absent from the SQL")
                continue
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

            # str() on a reflected type uses the *generic* dialect, where an enum renders
            # as VARCHAR(<longest label>) -- so the check above cannot tell an enum from a
            # varchar of the same width, nor spot a changed label set. Compare the labels.
            ea = getattr(a[column]["type"], "enums", None)
            eb = getattr(b[column]["type"], "enums", None)
            if ea != eb:
                out.append(f"{table}.{column} enum labels: sql={ea} models={eb}")
            # Strip the cast Postgres adds when reflecting, so 'user'::tag_source and
            # 'user' compare equal.
            da = (a[column].get("default") or "").split("::")[0].strip("'")
            db_ = (b[column].get("default") or "").split("::")[0].strip("'")
            if da != db_:
                out.append(f"{table}.{column} default: sql={da!r} models={db_!r}")

            # Identity is invisible to the checks above: SERIAL, GENERATED BY DEFAULT and
            # GENERATED ALWAYS all reflect as a plain bigint with no column default, and
            # they behave differently. ALWAYS rejects an explicit id outright.
            ia, ib = a[column].get("identity"), b[column].get("identity")
            if (ia is None) != (ib is None) or (
                ia is not None and ib is not None and ia.get("always") != ib.get("always")
            ):
                out.append(f"{table}.{column} identity: sql={ia} models={ib}")

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


def test_identity_columns_refuse_an_explicit_id(migrated):
    """GENERATED ALWAYS, not BY DEFAULT: nothing can quietly assign an id.

    An explicit id written past the sequence leaves it behind the data, and the next
    generated value collides -- long after whatever wrote it has been forgotten.
    """
    session, _ = migrated
    session.execute(text("INSERT INTO app_user (display_name) VALUES ('generated')"))
    session.commit()

    with pytest.raises(Exception, match="(?i)generated always|non-DEFAULT value"):
        session.execute(
            text("INSERT INTO app_user (id, display_name) VALUES (9999, 'explicit')")
        )
        session.commit()
    session.rollback()

    # The escape hatch exists for an importer preserving ids, and must be deliberate.
    session.execute(
        text(
            "INSERT INTO app_user (id, display_name) "
            "OVERRIDING SYSTEM VALUE VALUES (9999, 'imported')"
        )
    )
    session.commit()
    assert session.execute(
        text("SELECT count(*) FROM app_user WHERE id = 9999")
    ).scalar_one() == 1


def test_the_migration_survives_a_leftover_enum_type(pg_url, migrated):
    """Re-running after a partial teardown must work.

    The failure this covers: tables dropped by hand, the enum types left behind because
    nothing drops a type implicitly, and every subsequent `alembic upgrade head` dying on
    `type "tag_source" already exists`. Both revisions' types are left behind here, since
    0002 added `job_state` with the same hazard.
    """
    from alembic import command

    session, engine = migrated

    # Leave the database in exactly that state: tables gone, types still there. In
    # revision order reversed -- 0002's tables reference 0001's, so dropping 0001's first
    # fails on the foreign key rather than testing anything.
    drop_dir = ALEMBIC_INI.parent / "schema" / "drop"
    for script in ("drop_content.sql", "drop_tables.sql"):
        sql = (drop_dir / script).read_text()
        statements = "\n".join(
            line for line in sql.splitlines() if not line.lstrip().startswith("\\")
        )
        for keep in ("DROP TYPE IF EXISTS tag_source;", "DROP TYPE IF EXISTS job_state;"):
            statements = statements.replace(keep, "")
        session.execute(text(statements))
    session.execute(text("DROP TABLE IF EXISTS alembic_version"))
    session.commit()

    leftover = session.execute(
        text("SELECT count(*) FROM pg_type WHERE typname IN ('tag_source', 'job_state')")
    ).scalar_one()
    assert leftover == 2, "the fixture for this test did not leave the types behind"

    command.upgrade(alembic_config(pg_url), "head")

    present = set(inspect(engine).get_table_names())
    assert set(TABLES) <= present, "upgrade must succeed over leftover types"

