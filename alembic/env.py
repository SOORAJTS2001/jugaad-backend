import os
from logging.config import fileConfig
from dotenv import load_dotenv
from alembic import context
from sqlalchemy import pool

load_dotenv("local.env")
# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from models import Base

target_metadata = Base.metadata


# use it before the alembic migration on cli
# export DATABASE_URL=postgresql://user:pass@host:port/dbname


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and no DB Engine. Used for generating SQL migration scripts.
    """

    ASYNC_DB_URL = os.environ["DATABASE_URL"]
    SYNC_DB_URL = ASYNC_DB_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)

    context.configure(
        url=SYNC_DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # Optional but useful: detects type changes
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    from sqlalchemy import create_engine

    ASYNC_DB_URL = os.environ["DATABASE_URL"]
    SYNC_DB_URL = ASYNC_DB_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)

    connectable = create_engine(SYNC_DB_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
