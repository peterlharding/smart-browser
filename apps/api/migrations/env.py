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


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # Postgres assigns table ownership to whoever runs CREATE TABLE, so which role
        # this is matters as much as which database. Printed before any DDL runs, because
        # noticing afterwards means dropping and recreating.
        who = connection.execute(
            sa.text("SELECT current_user, current_database()")
        ).one()
        print(f"[alembic] connected to {who[1]!r} as {who[0]!r}")
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
