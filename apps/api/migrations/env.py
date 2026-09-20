"""Alembic environment.

The database URL comes from the application settings rather than alembic.ini, so there is
one place credentials live and `alembic upgrade head` cannot be pointed somewhere the app
is not.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from bookmarks_api.config import get_settings
from bookmarks_api.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Autogenerate is deliberately not relied upon: these migrations transform a schema that
# SQLAlchemy models do not yet describe (the v1 shape). target_metadata is set so that
# `--autogenerate` is available from M2 onward, when the models are the source of truth.
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
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
