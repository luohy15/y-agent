"""Database setup for PostgreSQL."""

import os
from contextlib import contextmanager
from typing import Optional

from dotenv import load_dotenv
from storage.global_config import load_global_config

load_dotenv()
load_global_config()

from contextvars import ContextVar

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from storage.entity.base import Base


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


# Connection-health bounds, so a DB call cannot hang on a socket that will
# never answer (todo 3226). Both are about *reaching* the server, not about
# how long its work may take: `connect_timeout` caps opening a connection, and
# the TCP keepalives detect a peer that vanished mid-statement (nothing
# server-side can fire when no packets get through). Neither can cancel valid
# work on a healthy connection, so they are safe to apply engine-wide;
# bounding statement duration is a per-workload decision and lives in
# `statement_timeout()` below.
_CONNECT_TIMEOUT_SECONDS = 10
_KEEPALIVE_IDLE_SECONDS = 30
_KEEPALIVE_INTERVAL_SECONDS = 10
_KEEPALIVE_FAILED_PROBES = 3


def _get_engine_kwargs(url: str) -> dict:
    if url.startswith("postgresql://") or url.startswith("postgresql+psycopg://"):
        return {
            "pool_pre_ping": True,
            "pool_size": 5,
            "max_overflow": 10,
            "pool_recycle": 3600,
            "pool_timeout": 5,
            "echo": False,
            "connect_args": {
                "connect_timeout": _CONNECT_TIMEOUT_SECONDS,
                "keepalives": 1,
                "keepalives_idle": _KEEPALIVE_IDLE_SECONDS,
                "keepalives_interval": _KEEPALIVE_INTERVAL_SECONDS,
                "keepalives_count": _KEEPALIVE_FAILED_PROBES,
            },
        }
    return {"echo": False}


def init_db(database_url: str):
    """Initialize the database engine and session factory."""
    global _engine, _SessionLocal

    if _engine is not None:
        return

    engine_kwargs = _get_engine_kwargs(database_url)

    _engine = create_engine(database_url, **engine_kwargs)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def init_tables():
    """Create all database tables defined in the entity models."""
    if _engine is None:
        database_url = os.getenv("DATABASE_URL_DEV", os.getenv("DATABASE_URL"))
        if database_url:
            init_db(database_url)
        else:
            raise RuntimeError("Database not initialized. Set DATABASE_URL_DEV or DATABASE_URL, or call init_db() first.")

    # Import all entities to register them with Base
    import storage.entity.user  # noqa: F401
    import storage.entity.bot_config  # noqa: F401
    import storage.entity.bot_route_state  # noqa: F401
    import storage.entity.vm_config  # noqa: F401
    import storage.entity.chat  # noqa: F401
    import storage.entity.todo  # noqa: F401
    import storage.entity.calendar_event  # noqa: F401
    import storage.entity.link  # noqa: F401
    import storage.entity.email  # noqa: F401
    import storage.entity.email_account  # noqa: F401
    import storage.entity.dev_worktree  # noqa: F401
    import storage.entity.tg_topic  # noqa: F401
    import storage.entity.trace_share  # noqa: F401
    import storage.entity.note_share  # noqa: F401
    import storage.entity.link_todo_relation  # noqa: F401
    import storage.entity.note  # noqa: F401
    import storage.entity.note_todo_relation  # noqa: F401
    import storage.entity.reminder  # noqa: F401
    import storage.entity.routine  # noqa: F401
    import storage.entity.rss_feed  # noqa: F401
    import storage.entity.entity  # noqa: F401
    import storage.entity.entity_note_relation  # noqa: F401
    import storage.entity.entity_rss_relation  # noqa: F401
    import storage.entity.entity_link_relation  # noqa: F401
    import storage.entity.entity_tag  # noqa: F401
    import storage.entity.user_preference  # noqa: F401
    import storage.entity.english_correction  # noqa: F401
    import storage.entity.user_cookies  # noqa: F401
    import storage.entity.model_usage_daily  # noqa: F401
    import storage.entity.model_usage_hourly  # noqa: F401
    import storage.entity.api_latency_event  # noqa: F401
    import storage.entity.api_latency_rollup  # noqa: F401
    import storage.entity.provider_status  # noqa: F401
    import storage.entity.module  # noqa: F401
    import storage.entity.module_version  # noqa: F401

    Base.metadata.create_all(bind=_engine)


def get_engine() -> Engine:
    """Return the process engine, auto-initializing like get_db() does.

    Read-only consumers (e.g. the module publish schema preflight, plan D7)
    use this instead of reaching for the private `_engine` global.
    """
    global _engine
    if _engine is None:
        database_url = os.getenv("DATABASE_URL_DEV", os.getenv("DATABASE_URL"))
        if database_url:
            init_db(database_url)
        else:
            raise RuntimeError("Database not initialized. Set DATABASE_URL_DEV or DATABASE_URL, or call init_db() first.")
    return _engine


@contextmanager
def get_db() -> Session:
    """Context manager that yields a SQLAlchemy session."""
    if _SessionLocal is None:
        # Auto-initialize from DATABASE_URL env var
        database_url = os.getenv("DATABASE_URL_DEV", os.getenv("DATABASE_URL"))
        if database_url:
            init_db(database_url)
        else:
            raise RuntimeError("Database not initialized. Set DATABASE_URL_DEV or DATABASE_URL, or call init_db() first.")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Statement duration is bounded per workload, never engine-wide: a global
# cutoff would also cancel valid long work elsewhere (bulk writes, rollup
# window replacement, DDL from init_tables, transactions waiting on a row
# lock). Only a caller that knows its own statements are short opts in.
#
# The one caller today is the usage-limit refresh path (todo 3226), whose DB
# work runs in executor threads nothing can cancel: `asyncio.wait_for` frees
# the awaiter, never the thread, so without a server-side bound a stalled
# statement would keep a thread and its pooled connection indefinitely.
_statement_timeout_ms: ContextVar[int | None] = ContextVar("statement_timeout_ms", default=None)


@contextmanager
def statement_timeout(seconds: float):
    """Bound every statement issued inside this context (PostgreSQL only).

    The value is applied with `SET LOCAL` on each transaction as it begins, so
    it reverts at commit/rollback and can never leak to the next user of a
    pooled connection — and, because it is re-applied per transaction rather
    than once per session, a caller that commits mid-session stays bounded.

    Scope is the current context (an executor thread has its own), not the
    engine: opting in is the caller's statement about its own queries.
    """
    token = _statement_timeout_ms.set(int(seconds * 1000))
    try:
        yield
    finally:
        _statement_timeout_ms.reset(token)


@event.listens_for(Session, "after_begin")
def _apply_statement_timeout(session, transaction, connection):
    timeout_ms = _statement_timeout_ms.get()
    if timeout_ms is None or connection.dialect.name != "postgresql":
        return
    connection.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_ms}")
