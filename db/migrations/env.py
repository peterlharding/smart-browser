"""Alembic environment.

Standalone by design. `db/` is the project's schema, not the API service's, so a migration
must not require the API package to be installed -- `alembic upgrade head` needs only
alembic, sqlalchemy and psycopg.

The database URL comes from `dburl.py`, which reads the same `.env` files the application
reads. `bookmarks_api` is imported only for `--autogenerate`, and only if it happens to be
available; without it every other alembic command still works.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

import sqlalchemy as sa
from alembic import context
from sqlalchemy import engine_from_config, pool

# alembic loads this file by path, so its directory is not importable by default.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dburl import resolve_database_url  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url", None):
    # `alembic -x db_url=...` beats everything, for a scratch database or a recovery.
    x_args = context.get_x_argument(as_dictionary=True)
    config.set_main_option("sqlalchemy.url", resolve_database_url(x_args.get("db_url")))

# Only needed for `alembic revision --autogenerate`, which compares the models against the
# database. Optional on purpose: requiring the API package here would make the schema tree
# depend on one of the services that uses it.
#
# Autogenerate is reliable for tables and columns and blind to server defaults, enum
# changes and anything needing a data migration -- and the DDL in this project is written
# by hand in db/schema/create anyway, so this is a cross-check rather than a generator.
try:
    from bookmarks_api.db import Base

    import bookmarks_api.models  # noqa: F401  registers the tables on Base

    target_metadata = Base.metadata
except ModuleNotFoundError:
    target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def announce(connectable: sa.Engine) -> None:
    """Say which database and role the migration is about to act as.

    On a connection of its own, and that is not incidental. SQLAlchemy 2.0 opens a
    transaction on a connection's first `execute()`, and alembic's `begin_transaction()`
    returns a no-op when the connection it was handed is already in one -- so nothing
    commits, closing the connection rolls the migration back, and alembic still logs
    "Running upgrade" and exits 0. A probe on the migration's own connection therefore
    silently discards every migration it was meant to make legible.

    Postgres assigns table ownership to whoever runs CREATE TABLE, so the role is worth
    printing; noticing it afterwards means dropping and recreating.
    """
    if connectable.dialect.name != "postgresql":
        return
    try:
        with connectable.connect() as probe:
            who = probe.execute(sa.text("SELECT current_user, current_database()")).one()
    except Exception as exc:  # noqa: BLE001 - never let a diagnostic stop a migration
        print(f"[alembic] could not identify the connection: {exc}")
        return
    print(f"[alembic] connected to {who[1]!r} as {who[0]!r}")


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    announce(connectable)

    # Nothing may execute on this connection before context.configure(). See announce().
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
