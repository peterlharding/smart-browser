"""Guards for the alembic setup and the schema SQL it runs.

Two classes of failure live here, both silent.

**env.py's transaction trap.** A migration once reported success -- "Running upgrade ->
0001", exit 0, no error -- and left an empty database. env.py had executed a diagnostic
query on the migration's connection before `context.configure()`. SQLAlchemy 2.0 opens a
transaction on a connection's first `execute()`, alembic's `begin_transaction()` returns a
*no-op* when handed a connection already in one, so nothing committed and closing the
connection rolled it all back. Proven against real Postgres:

    probe on the migration connection
        in_transaction() True,  begin_transaction() -> None,  0 tables created
    probe on its own connection
        in_transaction() False, begin_transaction() -> real,  8 tables created

SQLite does not reproduce it -- alembic uses non-transactional DDL there and commits
regardless -- so the behavioural test is in the Postgres suite and this static one exists
because that suite is opt-in.

**Manifest drift.** The schema is a set of .sql files ordered by create_tables.sql. A file
missing from the manifest is a table that never gets created; a name in the manifest with
no file is a build that dies half way.
"""

import ast
import re
from pathlib import Path

from bookmarks_api.config import MIGRATIONS_DIR

ENV_PY = MIGRATIONS_DIR / "env.py"
SCHEMA_DIR = MIGRATIONS_DIR.parent / "schema"
CREATE_DIR = SCHEMA_DIR / "create"
MANIFEST = CREATE_DIR / "create_tables.sql"

INCLUDE = re.compile(r"^\s*\\ir?\s+(\S+)\s*;?\s*$", re.MULTILINE)


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(ENV_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in {ENV_PY}")


def _manifest_names() -> list[str]:
    return INCLUDE.findall(MANIFEST.read_text())


# --- env.py ------------------------------------------------------------------


def test_nothing_executes_on_the_migration_connection_before_configure():
    """The whole bug in one assertion."""
    online = _function("run_migrations_online")

    configure_line = next(
        (
            node.lineno
            for node in ast.walk(online)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "configure"
        ),
        None,
    )
    assert configure_line is not None, "run_migrations_online must call context.configure"

    early = [
        node.lineno
        for node in ast.walk(online)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        and node.lineno < configure_line
    ]
    assert not early, (
        f"env.py executes a statement at line(s) {early}, before context.configure() on "
        f"line {configure_line}. That opens a transaction, which makes alembic's "
        f"begin_transaction() a no-op, which means migrations are rolled back on close "
        f"while still reporting success. Put it on its own connection."
    )


def test_the_diagnostic_takes_an_engine_not_a_connection():
    """`announce` must open its own connection, so it cannot be handed the wrong one."""
    announce = _function("announce")
    (arg,) = announce.args.args
    assert arg.arg == "connectable", "announce() should take the engine, not a connection"
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect"
        for node in ast.walk(announce)
    ), "announce() must call .connect() itself"


def test_a_preset_url_is_respected():
    """Without this, alembic can only ever point where the settings point.

    Tests needing a scratch database, and anyone recovering a database that is not the
    configured one, both need the override.
    """
    assert "if not config.get_main_option" in ENV_PY.read_text(), (
        "env.py must not overwrite an explicitly configured sqlalchemy.url"
    )


# --- the schema files --------------------------------------------------------


def test_every_file_the_manifest_names_exists():
    named = _manifest_names()
    assert named, "create_tables.sql names no files"
    missing = [name for name in named if not (CREATE_DIR / name).exists()]
    assert not missing, f"named by the manifest but absent: {missing}"


def test_every_create_file_is_in_the_manifest():
    """A file nobody includes is a table that never gets created."""
    on_disk = {path.name for path in CREATE_DIR.glob("*.sql")} - {MANIFEST.name}
    orphans = sorted(on_disk - set(_manifest_names()))
    assert not orphans, f"in schema/create but not in create_tables.sql: {orphans}"


def test_create_files_carry_no_drop_statements():
    """A DROP on the upgrade path is silent data loss when a migration is re-run.

    The convention elsewhere puts `DROP TABLE IF EXISTS` at the head of each create file
    so a rebuild is idempotent. That is right for building a database from nothing and
    wrong for a migration, so drops live in schema/drop/ instead.
    """
    offenders = [
        path.name
        for path in CREATE_DIR.glob("*.sql")
        if re.search(r"^\s*DROP\s", path.read_text(), re.IGNORECASE | re.MULTILINE)
    ]
    assert not offenders, f"DROP found in schema/create: {offenders}"


def test_the_drop_script_reverses_the_create_order():
    """Dropping in creation order fails on the first foreign key."""
    created = [Path(name).stem for name in _manifest_names()]
    drop_sql = (SCHEMA_DIR / "drop" / "drop_tables.sql").read_text()
    dropped = re.findall(
        r"^\s*DROP\s+(?:TABLE|TYPE)\s+IF\s+EXISTS\s+(\w+)",
        drop_sql,
        re.IGNORECASE | re.MULTILINE,
    )

    assert set(dropped) == set(created), (
        f"create and drop cover different objects: "
        f"only created={sorted(set(created) - set(dropped))} "
        f"only dropped={sorted(set(dropped) - set(created))}"
    )
    assert dropped == list(reversed(created)), (
        f"drop order must reverse create order\n  create: {created}\n  drop:   {dropped}"
    )


def _without_comments(sql: str) -> str:
    """Strip `--` comments. A rule about SQL should not be tripped by prose about SQL."""
    return "\n".join(re.sub(r"--.*$", "", line) for line in sql.splitlines())


def test_the_tag_check_constraint_is_portable_sql():
    """`btrim` is Postgres-only and blocks running the schema anywhere else."""
    tag_sql = _without_comments((CREATE_DIR / "tag.sql").read_text())
    assert "btrim(" not in tag_sql, "use trim(), which is standard SQL"
    assert "length(trim(name)) > 0" in tag_sql


def test_no_create_file_uses_postgres_only_string_functions():
    """Applies the same rule to every file, not just the one that broke."""
    postgres_only = ("btrim(", "ltrim(", "rtrim(")
    offenders = {
        path.name: [fn for fn in postgres_only if fn in _without_comments(path.read_text())]
        for path in CREATE_DIR.glob("*.sql")
    }
    found = {name: fns for name, fns in offenders.items() if fns}
    assert not found, f"Postgres-only string functions in schema/create: {found}"


def test_the_revision_refuses_meta_commands_it_cannot_run():
    """A psql meta-command silently skipped is DDL silently not run."""
    revision = (MIGRATIONS_DIR / "versions" / "0001_initial_schema.py").read_text()
    assert "_strip_meta_commands" in revision
    assert "is not supported" in revision, (
        "the runner must raise on an unknown meta-command, not skip it"
    )
