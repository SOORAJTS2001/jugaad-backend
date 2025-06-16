import os

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import declarative_base

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")
MAILER_ADDRESS = os.getenv("MAILER_ADDRESS")
MAILER_PASSWORD = os.getenv("MAILER_PASSWORD")


if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    connect_args = {}

async_engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL, connect_args=connect_args, echo=False  # echo=True for SQL logging
)
Base = declarative_base()

__all__ = ["Base", "async_engine", "MAILER_ADDRESS", "MAILER_PASSWORD"]
