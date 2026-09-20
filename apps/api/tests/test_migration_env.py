"""Guard the alembic env.py trap that silently discards migrations.

A migration once reported success -- "Running upgrade -> 0001", exit 0, no error -- and
left an empty database. The cause: env.py executed a diagnostic query on the migration's
connection before `context.configure()`. SQLAlchemy 2.0 opens a transaction on a
connection's first `execute()`, alembic's `begin_transaction()` returns a *no-op* when
handed a connection already in one, so nothing committed and closing the connection rolled
everything back.

Proven against real Postgres:

    probe on the migration connection
        in_transaction() True,  begin_transaction() -> None,  0 tables created
    probe on its own connection
        in_transaction() False, begin_transaction() -> real,  8 tables created

SQLite does not reproduce it -- alembic uses non-transactional DDL there and commits
anyway -- so the behavioural test lives in the Postgres suite, and this static one exists
because that suite is opt-in and this failure mode is invisible when it is not run.
"""

import ast

from bookmarks_api.config import MIGRATIONS_DIR

ENV_PY = MIGRATIONS_DIR / "env.py"


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(ENV_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in {ENV_PY}")


def test_nothing_executes_on_the_migration_connection_before_configure():
    """The whole bug in one assertion."""
    online = _function("run_migrations_online")

    configure_line = None
    for node in ast.walk(online):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "configure"
        ):
            configure_line = node.lineno
            break

    assert configure_line is not None, "run_migrations_online must call context.configure"

    executes = [
        node.lineno
        for node in ast.walk(online)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    ]
    early = [line for line in executes if line < configure_line]
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

    opens_its_own = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect"
        for node in ast.walk(announce)
    )
    assert opens_its_own, "announce() must call .connect() itself"


def test_a_preset_url_is_respected():
    """Without this, alembic can only ever point where the settings point.

    Tests that need a scratch database, and anyone recovering a database that is not the
    configured one, both need to override it.
    """
    source = ENV_PY.read_text()
    assert "if not config.get_main_option" in source, (
        "env.py must not overwrite an explicitly configured sqlalchemy.url"
    )


def test_the_check_constraint_is_portable_sql():
    """`btrim` is Postgres-only and blocks running the migration anywhere else."""
    migration = (
        ENV_PY.parent / "versions" / "0001_initial_schema.py"
    ).read_text()
    assert "btrim" not in migration, "use trim(), which is standard SQL"
    assert "length(trim(name)) > 0" in migration
