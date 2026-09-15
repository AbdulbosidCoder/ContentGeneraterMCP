"""SQLAlchemy engine and session helpers."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from common import config

logger = logging.getLogger("common.db")


@lru_cache(maxsize=1)
def engine() -> Engine:
    return create_engine(config.database_url(), pool_pre_ping=True, pool_size=10, max_overflow=10)


@lru_cache(maxsize=1)
def session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def wait_for_database(timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            if time.monotonic() > deadline:
                raise
            logger.info("Waiting for database: %s", exc.__class__.__name__)
            time.sleep(2)


# create_all() only creates missing tables; columns added to existing tables later are
# applied here idempotently. Replace with Alembic migrations before production.
_COLUMN_MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS facebook_id VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_facebook_id ON users (facebook_id)",
]


def create_schema() -> None:
    """Create tables if missing. Uses an advisory lock so concurrent starts don't race."""
    from common.models import Base

    with engine().begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(724119)"))
        Base.metadata.create_all(conn)
        for statement in _COLUMN_MIGRATIONS:
            conn.execute(text(statement))
