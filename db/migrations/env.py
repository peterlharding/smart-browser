"""Alembic environment.

The database URL comes from the application settings rather than alembic.ini, so there is
one place credentials live and `alembic upgrade head` cannot be pointed somewhere the app
is not.
"""

from __future__ import annotations

from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import engine_from_config, pool

from bookmarks_api.config import get_settings
from bookmarks_api.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

# The models are the source of truth for the schema, so `alembic revision --autogenerate`
# works. Review what it produces: it is reliable for columns and tables, and blind to
# server defaults, enum changes and anything needing a data migration.
target_metadata = Base.metadata


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
