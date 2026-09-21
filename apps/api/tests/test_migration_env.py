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

import pytest

from bookmarks_api.config import MIGRATIONS_DIR

ENV_PY = MIGRATIONS_DIR / "env.py"
SCHEMA_DIR = MIGRATIONS_DIR.parent / "schema"
CREATE_DIR = SCHEMA_DIR / "create"
# One manifest per Alembic revision, each paired with the drop script that reverses it.
# Deliberately not nested: the runner executes the files a manifest names, so a manifest
# naming another manifest would run a file of meta-commands and quietly do nothing.
MANIFESTS = {
    "0001": (CREATE_DIR / "create_tables.sql", SCHEMA_DIR / "drop" / "drop_tables.sql"),
    "0002": (CREATE_DIR / "create_content.sql", SCHEMA_DIR / "drop" / "drop_content.sql"),
}
MANIFEST = MANIFESTS["0001"][0]

INCLUDE = re.compile(r"^\s*\\ir?\s+(\S+)\s*;?\s*$", re.MULTILINE)


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(ENV_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in {ENV_PY}")


def _manifest_names(manifest: Path = MANIFEST) -> list[str]:
    return INCLUDE.findall(manifest.read_text())


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


@pytest.mark.parametrize("revision", sorted(MANIFESTS))
def test_every_file_the_manifest_names_exists(revision):
    manifest, _ = MANIFESTS[revision]
    named = _manifest_names(manifest)
    assert named, f"{manifest.name} names no files"
    missing = [name for name in named if not (CREATE_DIR / name).exists()]
    assert not missing, f"named by {manifest.name} but absent: {missing}"


def test_every_create_file_is_in_exactly_one_manifest():
    """A file nobody includes is a table that never gets created.

    Exactly one, not at least one: a file named by two revisions would be created twice,
    and the second run fails on a database that has already had the first.
    """
    manifests = {manifest.name for manifest, _ in MANIFESTS.values()}
    on_disk = {path.name for path in CREATE_DIR.glob("*.sql")} - manifests

    named: dict[str, list[str]] = {}
    for manifest, _ in MANIFESTS.values():
        for name in _manifest_names(manifest):
            named.setdefault(name, []).append(manifest.name)

    orphans = sorted(on_disk - set(named))
    assert not orphans, f"in schema/create but named by no manifest: {orphans}"

    twice = {name: where for name, where in named.items() if len(where) > 1}
    assert not twice, f"named by more than one manifest: {twice}"


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


@pytest.mark.parametrize("revision", sorted(MANIFESTS))
def test_the_drop_script_reverses_the_create_order(revision):
    """Dropping in creation order fails on the first foreign key."""
    manifest, drop_script = MANIFESTS[revision]
    created = [Path(name).stem for name in _manifest_names(manifest)]
    drop_sql = drop_script.read_text()
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
    runner = (MIGRATIONS_DIR / "sqlrunner.py").read_text()
    assert "strip_meta_commands" in runner
    assert "is not supported" in runner, (
        "the runner must raise on an unknown meta-command, not skip it"
    )


# --- the shipped alembic.ini -------------------------------------------------


def test_alembic_ini_resolves_from_any_working_directory(tmp_path, monkeypatch):
    """Load the shipped config, from somewhere else, and find the revisions.

    `script_location = migrations` is resolved against the *working directory*, not
    against alembic.ini, so it worked only while alembic happened to be run from db/.
    `make migrate` runs from the repo root and died with "Path doesn't exist: migrations".

    Every other test here builds its own Config and sets script_location explicitly, which
    is precisely why a broken shipped value survived a green suite. This one uses the file
    as shipped.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from bookmarks_api.config import ALEMBIC_INI

    monkeypatch.chdir(tmp_path)  # no ./migrations here
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))

    revisions = [rev.revision for rev in script.walk_revisions()]
    assert revisions, "the shipped alembic.ini found no revisions"


def test_no_setting_in_alembic_ini_is_relative_to_the_working_directory():
    """Catch the next one of these before it ships.

    Path settings must be absolute or anchored with %(here)s. This has now bitten twice --
    once for .env, once for script_location -- and both times the symptom was something
    working from one directory and not another.
    """
    from bookmarks_api.config import ALEMBIC_INI

    path_settings = ("script_location", "prepend_sys_path", "version_locations")
    offenders = []
    for line in ALEMBIC_INI.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key, value = key.strip(), value.strip()
        if key in path_settings and value:
            anchored = value.startswith(("/", "%(here)s"))
            if not anchored:
                offenders.append(f"{key} = {value}")

    assert not offenders, (
        "relative path(s) in alembic.ini, resolved against the working directory rather "
        f"than the file: {offenders}. Use %(here)s/."
    )


def test_the_drop_script_leaves_alembic_version_alone():
    """It is the downgrade body, and alembic writes to that table straight afterwards.

    Dropping it there would break the very downgrade it implements. Resetting a database
    to nothing is a different operation, and `make schema-drop` does it separately.
    """
    drop_sql = (SCHEMA_DIR / "drop" / "drop_tables.sql").read_text()
    statements = _without_comments(drop_sql)
    assert "alembic_version" not in statements, (
        "drop_tables.sql must not drop alembic_version -- it runs as the downgrade"
    )


def test_the_enum_is_created_idempotently():
    """Postgres has no CREATE TYPE IF NOT EXISTS, and a type survives a table drop.

    A bare CREATE TYPE makes the migration impossible to re-run after any partial
    failure, which is exactly what happened: `type "tag_source" already exists`.
    """
    sql = _without_comments((CREATE_DIR / "tag_source.sql").read_text())
    assert "IF NOT EXISTS" in sql, "guard the creation"
    assert "RAISE EXCEPTION" in sql, (
        "an existing type with different labels must stop the migration, not be ignored"
    )


# --- revision 0002's precondition --------------------------------------------


def _revision_0002():
    """Import the revision module the way alembic does, by path.

    `prepend_sys_path` puts `db/migrations` on the path for alembic itself; this test
    imports one revision directly, so it does the same thing explicitly.
    """
    import importlib.util
    import sys

    sys.path.insert(0, str(MIGRATIONS_DIR))
    try:
        path = MIGRATIONS_DIR / "versions" / "0002_content_and_crawl_queue.py"
        spec = importlib.util.spec_from_file_location("revision_0002", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(MIGRATIONS_DIR))


def test_the_missing_extension_message_names_the_command_that_fixes_it():
    """Whichever branch it takes, it must end somewhere actionable.

    pgvector cannot be installed by the role that runs migrations, so this message is the
    entire remedy: a reader who gets `type "vector" does not exist` three statements later
    has to work out the privilege rule for themselves.
    """
    module = _revision_0002()

    installed_elsewhere = module.pgvector_message("0.8.5")
    assert "0.8.5" in installed_elsewhere
    assert "make db-bootstrap" in installed_elsewhere
    assert "superuser" in installed_elsewhere

    not_there_at_all = module.pgvector_message(None)
    assert "pgvector/pgvector" in not_there_at_all, "say which image ships it"
    assert "db-bootstrap" in not_there_at_all
