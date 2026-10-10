"""
ResQLink Alembic environment.

This project's migrations are written as raw SQL (via op.execute) rather than
SQLAlchemy Table/Column metadata, because the schema leans heavily on
PostgreSQL/PostGIS-specific features (geography columns, CHECK constraints,
PL/pgSQL trigger functions) that are more directly and unambiguously
expressed as SQL than reconstructed through the ORM's DDL layer. Because of
that, `target_metadata` is left as None: `alembic revision --autogenerate` is
NOT supported here — every revision in versions/ is written by hand, which is
also why the task asks for "one revision per logical schema change."
"""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Allow overriding the DSN via environment variable so CI / local dev / docker
# can all point at different databases without editing alembic.ini.
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

target_metadata = None  # raw-SQL migrations; see module docstring


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (for `alembic upgrade --sql`)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
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
